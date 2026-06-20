"""Runner for single-combined-onnx supercombo models (deep_rl3 / a40fa3a style).

One `driving_supercombo.onnx` compiles to a single `run_policy` JIT plus per-camera warp
JITs; all vision + policy outputs live in one `output_slices`. Temporal feature feedback
(`prev_feat` = last frame's `hidden_state`) is managed here, not inside the JIT.

    out = {
      'metadata': {'output_slices':..., 'input_shapes':..., ...},
      'run_policy': TinyJit(img, big_img, feat_q, desire_q, packed_npy_inputs) -> (out,),
      (cam_w, cam_h): TinyJit(img_q, big_img_q, tfm, big_tfm, frame, big_frame) -> (img, big_img),
    }
"""
from __future__ import annotations

import math
import os
import pickle
from typing import Any

import numpy as np

from openpilot.iqpilot.modeld_v2.parse_model_outputs_split import Parser as SplitParser
from openpilot.iqpilot.models.runners.constants import CUSTOM_MODEL_PATH, NumpyDict, ShapeDict, SliceDict
from openpilot.iqpilot.models.runners.model_runner import ModelRunner
from openpilot.iqpilot.models.split_model_constants import SplitModelConstants


def _tinygrad_imports():
    from tinygrad.tensor import Tensor
    from tinygrad.device import Device
    return Tensor, Device


class TinygradSupercomboRunner(ModelRunner):
    """Runs a single combined supercombo pkl. Bundle ships one `driving_supercombo_*` artifact."""

    uses_opencl_warp: bool = False

    def __init__(self):
        super().__init__()
        self._constants = SplitModelConstants
        self._parser = SplitParser()

        if len(self.models) != 1:
            raise ValueError(f"supercombo bundle must have exactly one artifact, got {list(self.models)}")
        self._model_data = next(iter(self.models.values()))

        pkl_path = os.path.join(CUSTOM_MODEL_PATH, self._model_data.model.artifact.fileName)
        with open(pkl_path, 'rb') as f:
            self._m: dict[Any, Any] = pickle.load(f)

        self._meta = self._m['metadata']
        self._ish = self._meta['input_shapes']
        self._slices = {k: v for k, v in self._meta['output_slices'].items() if k != 'pad'}
        self._hidden_slice = self._meta['output_slices']['hidden_state']
        self._run_policy = self._m['run_policy']
        self._warp_jits: dict[tuple[int, int], Any] = {k: v for k, v in self._m.items() if isinstance(k, tuple)}
        if not self._warp_jits:
            raise ValueError("supercombo pkl has no warp JITs")
        self._frame_skip = int(self._m.get('frame_skip', 4))

        self._queues: dict[str, Any] | None = None
        self._npy: dict[str, np.ndarray] | None = None
        self._cam: tuple[int, int] | None = None
        self._prev_desire = np.zeros(self._ish['desire_pulse'][2], dtype=np.float32)
        self._blob_cache: dict[tuple[str, int], Any] = {}

    def _frame_tensor(self, key: str, buf):
        Tensor, Device = _tinygrad_imports()
        arr = np.frombuffer(buf.data, dtype=np.uint8)
        ck = (key, arr.ctypes.data)
        t = self._blob_cache.get(ck)
        if t is None:
            t = Tensor.from_blob(arr.ctypes.data, (arr.size,), dtype='uint8', device=Device.DEFAULT)
            self._blob_cache[ck] = t
        return t

    @property
    def vision_input_names(self) -> list[str]:
        return ['img', 'big_img']

    @property
    def input_shapes(self) -> ShapeDict:
        return dict(self._ish)

    @property
    def output_slices(self) -> SliceDict:
        return dict(self._slices)

    def prepare_inputs(self, imgs_cl, numpy_inputs, frames):
        raise RuntimeError("supercombo runner has no OpenCL path; use run_fused()")

    def _ensure_queues(self, cam_w: int, cam_h: int) -> None:
        if self._queues is not None and self._cam == (cam_w, cam_h):
            return
        if (cam_w, cam_h) not in self._warp_jits:
            raise RuntimeError(f"no warp JIT for {cam_w}x{cam_h}; have {sorted(self._warp_jits)}")

        Tensor, Device = _tinygrad_imports()
        fs = self._frame_skip
        img = self._ish['img']
        n_frames = img[1] // 6
        img_buf = (fs * (n_frames - 1) + 1, 6, img[2], img[3])
        fb = self._ish['features_buffer']
        dp = self._ish['desire_pulse']
        tc = self._ish['traffic_convention']
        at = self._ish['action_t']

        zeros_u8 = lambda s: Tensor(np.zeros(s, dtype=np.uint8), device=Device.DEFAULT).contiguous().realize()
        zeros_f32 = lambda s: Tensor(np.zeros(s, dtype=np.float32), device=Device.DEFAULT).contiguous().realize()

        # packed npy block (single NPY tensor, mutated in place via views): order matches run_policy.split
        shapes = {'desire': (dp[2],), 'traffic_convention': tuple(tc), 'action_t': tuple(at), 'prev_feat': (fb[0], fb[2])}
        sizes = [math.prod(s) for s in shapes.values()]
        packed = np.zeros(sum(sizes), dtype=np.float32)
        views = {k: v.reshape(s) for (k, s), v in zip(shapes.items(), np.split(packed, np.cumsum(sizes[:-1])), strict=True)}

        self._npy = {'tfm': np.zeros((3, 3), dtype=np.float32), 'big_tfm': np.zeros((3, 3), dtype=np.float32), **views}
        self._queues = {
            'img_q':     zeros_u8(img_buf),
            'big_img_q': zeros_u8(img_buf),
            'feat_q':    zeros_f32((fs * fb[1], fb[0], fb[2])),
            'desire_q':  zeros_f32((fs * dp[1], dp[0], dp[2])),
            'tfm':       Tensor(self._npy['tfm'], device='NPY'),
            'big_tfm':   Tensor(self._npy['big_tfm'], device='NPY'),
            'packed_npy_inputs': Tensor(packed, device='NPY'),
        }
        self._cam = (cam_w, cam_h)

    def run_fused(self, bufs: dict, transforms: dict[str, np.ndarray], numpy_inputs: NumpyDict) -> NumpyDict:
        Tensor, Device = _tinygrad_imports()
        main_buf = bufs['img']
        self._ensure_queues(main_buf.width, main_buf.height)
        assert self._queues is not None and self._npy is not None

        self._npy['tfm'][:] = transforms['img']
        self._npy['big_tfm'][:] = transforms['big_img']

        desire_key = next((k for k in numpy_inputs if k.startswith('desire')), None)
        cur = numpy_inputs[desire_key].copy() if desire_key is not None else np.zeros_like(self._prev_desire)
        cur[0] = 0
        self._npy['desire'][:] = np.where(cur - self._prev_desire > .99, cur, 0)
        self._prev_desire[:] = cur
        if 'traffic_convention' in numpy_inputs:
            self._npy['traffic_convention'][:] = numpy_inputs['traffic_convention']
        if 'action_t' in numpy_inputs:
            self._npy['action_t'][:] = numpy_inputs['action_t']
        # self._npy['prev_feat'] holds last frame's hidden_state (zeros on the first frame)

        frame = self._frame_tensor('img', bufs['img'])
        big_frame = self._frame_tensor('big_img', bufs['big_img'])

        warp = self._warp_jits[self._cam]
        img, big_img = warp(img_q=self._queues['img_q'], big_img_q=self._queues['big_img_q'],
                            tfm=self._queues['tfm'], big_tfm=self._queues['big_tfm'], frame=frame, big_frame=big_frame)

        out, = self._run_policy(img=img, big_img=big_img, feat_q=self._queues['feat_q'],
                                desire_q=self._queues['desire_q'], packed_npy_inputs=self._queues['packed_npy_inputs'])
        flat = out.numpy().flatten()

        # feed hidden_state back as prev_feat for the next frame
        self._npy['prev_feat'][:] = flat[self._hidden_slice].reshape(self._npy['prev_feat'].shape)

        sliced = {k: flat[np.newaxis, sl] for k, sl in self._slices.items()}
        return self._parser.parse_vision_outputs(sliced)  # single-pass; parse_outputs double-parses a combined dict

    def _run_model(self) -> NumpyDict:
        raise RuntimeError("supercombo path goes through run_fused(), not _run_model()")
