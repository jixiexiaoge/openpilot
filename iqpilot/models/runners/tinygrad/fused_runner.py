"""Runner for fused single-pkl models (op_model16_deep style).

The fused pkl bakes the camera warp, vision encoder and on/off policy heads into
one tinygrad JIT plus per-camera-resolution warp JITs, and carries the
vision/on_policy/off_policy metadata internally:

    out = {
      'metadata': {'vision': ..., 'on_policy': ..., 'off_policy': ...},
      'run_policy': TinyJit(img, big_img, feat_q, desire_q, desire, traffic_convention, action_t),
      (cam_w, cam_h): TinyJit(img_q, big_img_q, tfm, big_tfm, frame, big_frame),
      ...
    }
"""
from __future__ import annotations

import os
import pickle
from typing import Any

import numpy as np

from openpilot.iqpilot.modeld_v2.parse_model_outputs_split import Parser as SplitParser
from openpilot.iqpilot.models.runners.constants import (
    CUSTOM_MODEL_PATH, NumpyDict, ShapeDict, SliceDict,
)
from openpilot.iqpilot.models.runners.model_runner import ModelRunner
from openpilot.iqpilot.models.split_model_constants import SplitModelConstants


def _tinygrad_imports():
    from tinygrad.tensor import Tensor
    from tinygrad.device import Device
    return Tensor, Device


WARP_DEV = os.getenv('WARP_DEV')


class TinygradFusedRunner(ModelRunner):
    """Runs a fused warp+vision+policy pkl. Bundle ships one `driving_fused_*` artifact."""

    uses_opencl_warp: bool = False

    def __init__(self):
        super().__init__()

        self._constants = SplitModelConstants
        self._parser = SplitParser()

        if len(self.models) != 1:
            raise ValueError(f"fused bundle must have exactly one artifact, got {list(self.models)}")
        self._model_data = next(iter(self.models.values()))

        pkl_path = os.path.join(CUSTOM_MODEL_PATH, self._model_data.model.artifact.fileName)
        with open(pkl_path, 'rb') as f:
            self._fused: dict[Any, Any] = pickle.load(f)

        self._vision_meta = self._fused['metadata']['vision']
        self._on_meta = self._fused['metadata']['on_policy']
        self._off_meta = self._fused['metadata']['off_policy']
        self._run_policy = self._fused['run_policy']
        self._warp_jits: dict[tuple[int, int], Any] = {k: v for k, v in self._fused.items() if isinstance(k, tuple)}
        if not self._warp_jits:
            raise ValueError("fused pkl has no warp JITs")

        self._frame_skip: int = int(self._fused.get('frame_skip', 4))

        self._queues: dict[str, Any] | None = None
        self._npy_buffers: dict[str, np.ndarray] | None = None
        self._cam_resolution: tuple[int, int] | None = None

    @property
    def vision_input_names(self) -> list[str]:
        return ['img', 'big_img']

    @property
    def input_shapes(self) -> ShapeDict:
        return {**self._vision_meta['input_shapes'], **self._on_meta['input_shapes']}

    @property
    def output_slices(self) -> SliceDict:
        merged: SliceDict = {}
        for src in (self._vision_meta['output_slices'], self._on_meta['output_slices'], self._off_meta['output_slices']):
            merged.update({k: v for k, v in src.items() if k != 'pad'})
        return merged

    def prepare_inputs(self, imgs_cl, numpy_inputs, frames):
        raise RuntimeError("fused runner has no OpenCL path; use run_fused()")

    def _ensure_queues(self, cam_w: int, cam_h: int) -> None:
        if self._queues is not None and self._cam_resolution == (cam_w, cam_h):
            return
        if (cam_w, cam_h) not in self._warp_jits:
            raise RuntimeError(f"no warp JIT for {cam_w}x{cam_h}; have {sorted(self._warp_jits)}")

        Tensor, Device = _tinygrad_imports()
        img_shape = self._vision_meta['input_shapes']['img']
        fb = self._on_meta['input_shapes']['features_buffer']
        dp = self._on_meta['input_shapes']['desire_pulse']
        n_frames = img_shape[1] // 6
        img_buf_shape = (self._frame_skip * (n_frames - 1) + 1, 6, img_shape[2], img_shape[3])

        zeros_u8 = lambda shp: Tensor(np.zeros(shp, dtype=np.uint8), device=Device.DEFAULT).contiguous().realize()
        zeros_f32 = lambda shp: Tensor(np.zeros(shp, dtype=np.float32), device=Device.DEFAULT).contiguous().realize()

        self._queues = {
            'img_q':     zeros_u8(img_buf_shape),
            'big_img_q': zeros_u8(img_buf_shape),
            'feat_q':    zeros_f32((self._frame_skip * (fb[1] - 1) + 1, fb[0], fb[2])),
            'desire_q':  zeros_f32((self._frame_skip * dp[1], dp[0], dp[2])),
        }
        # shapes must match the captured run_policy JIT inputs
        on_shapes = self._on_meta['input_shapes']
        self._npy_buffers = {
            'desire':             np.zeros(dp[2], dtype=np.float32),
            'traffic_convention': np.zeros(on_shapes['traffic_convention'], dtype=np.float32),
            'action_t':           np.zeros(on_shapes['action_t'], dtype=np.float32),
            'tfm':                np.zeros((3, 3), dtype=np.float32),
            'big_tfm':            np.zeros((3, 3), dtype=np.float32),
        }
        self._cam_resolution = (cam_w, cam_h)

    def run_fused(self, bufs: dict, transforms: dict[str, np.ndarray], numpy_inputs: NumpyDict) -> NumpyDict:
        """warp + vision + policy in one pass from raw NV12 bufs + transform matrices."""
        Tensor, Device = _tinygrad_imports()

        main_buf = bufs['img']
        self._ensure_queues(main_buf.width, main_buf.height)
        assert self._queues is not None and self._npy_buffers is not None

        desire_key = next((k for k in numpy_inputs if k.startswith('desire')), None)
        if desire_key is not None:
            self._npy_buffers['desire'][:] = numpy_inputs[desire_key]
        if 'traffic_convention' in numpy_inputs:
            self._npy_buffers['traffic_convention'][:] = numpy_inputs['traffic_convention']
        if 'action_t' in numpy_inputs:
            self._npy_buffers['action_t'][:] = numpy_inputs['action_t']
        self._npy_buffers['tfm'][:] = transforms['img']
        self._npy_buffers['big_tfm'][:] = transforms['big_img']

        npy = lambda key: Tensor(self._npy_buffers[key], device='NPY')

        # frames go on the compute device to match the captured warp JIT
        frame = Tensor(bufs['img'].data, device=Device.DEFAULT).realize()
        big_frame = Tensor(bufs['big_img'].data, device=Device.DEFAULT).realize()

        warp_jit = self._warp_jits[self._cam_resolution]
        img, big_img = warp_jit(img_q=self._queues['img_q'], big_img_q=self._queues['big_img_q'],
                                tfm=npy('tfm'), big_tfm=npy('big_tfm'), frame=frame, big_frame=big_frame)

        vision_out_t, on_out_t, off_out_t = self._run_policy(
            img=img, big_img=big_img, feat_q=self._queues['feat_q'], desire_q=self._queues['desire_q'],
            desire=npy('desire'), traffic_convention=npy('traffic_convention'), action_t=npy('action_t'))

        # parse each model's output on its own sliced dict; parsing a merged dict
        # would run parse_dynamic_outputs twice and double-parse plan/lead
        def _slice(tensor_out, meta) -> NumpyDict:
            flat = tensor_out.numpy().flatten()
            return {k: flat[np.newaxis, sl] for k, sl in meta['output_slices'].items() if k != 'pad'}

        parsed: NumpyDict = {}
        parsed.update(self._parser.parse_vision_outputs(_slice(vision_out_t, self._vision_meta)))
        parsed.update(self._parser.parse_policy_outputs(_slice(off_out_t, self._off_meta)))
        parsed.update(self._parser.parse_policy_outputs(_slice(on_out_t, self._on_meta)))
        return parsed

    def _run_model(self) -> NumpyDict:
        raise RuntimeError("fused path goes through run_fused(), not _run_model()")
