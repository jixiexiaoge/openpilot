"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
from __future__ import annotations

import hashlib
import math
import os
import pickle
import re
from typing import Any

import numpy as np

from openpilot.common.params import Params
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import CUSTOM_MODEL_PATH, NumpyDict, ShapeDict, SliceDict
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import ModelRunner
from openpilot.iqpilot.selfdrive.iqmodeld.models.split_model_constants import SplitModelConstants
from openpilot.iqpilot.selfdrive.iqmodeld.parser import PhaseParser


def _tinygrad_imports():
    from tinygrad.tensor import Tensor
    from tinygrad.device import Device
    return Tensor, Device


def _captured_queue_depth(warp_jit: Any) -> int | None:
    captured = getattr(warp_jit, "captured", None)
    infos = getattr(captured, "expected_input_info", None)
    if not infos or len(infos) < 2:
        return None

    view_repr = repr(infos[1][0])
    dims = [int(val) for val in re.findall(r"arg=(\d+)", view_repr)]
    return dims[0] if len(dims) >= 4 else None


def _captured_devices(warp_jit: Any) -> set[str]:
    captured = getattr(warp_jit, "captured", None)
    infos = getattr(captured, "expected_input_info", None)
    if not infos:
        return set()

    devices: set[str] = set()
    for info in infos:
        if isinstance(info, tuple) and len(info) >= 4 and isinstance(info[3], str):
            devices.add(info[3])
    return devices


def _captured_expected_names(jit_obj: Any) -> list[str]:
    captured = getattr(jit_obj, "captured", None)
    names = getattr(captured, "expected_names", None)
    return list(names) if names else []


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_jit_arg_mismatch(err: BaseException) -> bool:
    return "args mismatch in JIT" in str(err)


class TinygradSupercomboRunner(ModelRunner):
    """Runs a single combined supercombo pkl. Bundle ships one `driving_supercombo_*` artifact."""

    uses_opencl_warp: bool = False

    def __init__(self):
        super().__init__()
        self._constants = SplitModelConstants
        self._parser = PhaseParser()

        if len(self.models) != 1:
            raise ValueError(f"supercombo bundle must have exactly one artifact, got {list(self.models)}")
        self._model_data = next(iter(self.models.values()))

        pkl_path = os.path.join(CUSTOM_MODEL_PATH, self._model_data.model.artifact.fileName)
        self._pkl_path = pkl_path
        self._expected_sha256 = getattr(getattr(self._model_data.model.artifact, "downloadUri", None), "sha256", "") or ""
        self._verify_artifact_file()
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
        self._validate_warp_jits(pkl_path)
        self._validate_jit_names()

        self._queues: dict[str, Any] | None = None
        self._npy: dict[str, np.ndarray] | None = None
        self._cam: tuple[int, int] | None = None
        self._prev_desire = np.zeros(self._ish['desire_pulse'][2], dtype=np.float32)
        self._blob_cache: dict[tuple[str, int], Any] = {}

    def _verify_artifact_file(self) -> None:
        if not self._expected_sha256:
            return

        actual_sha256 = _file_sha256(self._pkl_path)
        if actual_sha256 == self._expected_sha256:
            return

        try:
            os.remove(self._pkl_path)
        except OSError:
            pass
        redownload_msg = self._schedule_active_bundle_redownload()

        raise RuntimeError(
            "supercombo artifact SHA mismatch: "
            f"expected {self._expected_sha256}, got {actual_sha256} for {self._pkl_path}. "
            f"Deleted the stale cached file{redownload_msg}."
        )

    def _validate_warp_jits(self, pkl_path: str) -> None:
        img = self._ish['img']
        n_frames = img[1] // 6
        expected_depth = self._frame_skip * (n_frames - 1) + 1
        expected_device = os.getenv('DEV')

        mismatches: list[str] = []
        for cam, warp_jit in sorted(self._warp_jits.items()):
            captured_depth = _captured_queue_depth(warp_jit)
            captured_devices = _captured_devices(warp_jit)
            if captured_depth is not None and captured_depth != expected_depth:
                mismatches.append(
                    f"{cam[0]}x{cam[1]} queue-depth captured={captured_depth} expected={expected_depth}"
                )
            if expected_device and captured_devices and expected_device not in captured_devices:
                mismatches.append(
                    f"{cam[0]}x{cam[1]} device captured={sorted(captured_devices)} expected={expected_device}"
                )

        if mismatches:
            details = "; ".join(mismatches)
            raise RuntimeError(
                "supercombo warp JIT compatibility mismatch: "
                f"{details}. Bundle {pkl_path} was compiled with the wrong backend, frame_skip, or queue shape; "
                "re-download or rebuild this model artifact."
            )

    def _validate_jit_names(self) -> None:
        expected_warp_names = ['big_frame', 'big_tfm', 'frame', 'tfm']
        expected_policy_names = ['big_img_q', 'desire_q', 'feat_q', 'img_q', 'packed_npy_inputs', 'warped']

        mismatches: list[str] = []

        policy_names = sorted(_captured_expected_names(self._run_policy))
        if policy_names and policy_names != expected_policy_names:
            mismatches.append(f"run_policy captured={policy_names} expected={expected_policy_names}")

        for cam, warp_jit in sorted(self._warp_jits.items()):
            warp_names = sorted(_captured_expected_names(warp_jit))
            if warp_names and warp_names != expected_warp_names:
                mismatches.append(f"{cam[0]}x{cam[1]} warp captured={warp_names} expected={expected_warp_names}")

        if mismatches:
            details = "; ".join(mismatches)
            actual_sha = None
            try:
                actual_sha = _file_sha256(self._pkl_path)
            except OSError:
                pass

            if actual_sha and self._expected_sha256 and actual_sha != self._expected_sha256:
                try:
                    os.remove(self._pkl_path)
                except OSError:
                    pass
                redownload_msg = self._schedule_active_bundle_redownload()
                raise RuntimeError(
                    "supercombo artifact contract mismatch with stale cached SHA: "
                    f"{details}. Expected SHA {self._expected_sha256}, got {actual_sha}. "
                    f"Deleted the stale cached file{redownload_msg}."
                )

            raise RuntimeError(
                "supercombo artifact JIT argument mismatch: "
                f"{details}. This model file does not match the current IQPilot runtime contract. "
                "Re-download or rebuild this model artifact."
            )

    def _handle_runtime_jit_mismatch(self, err: BaseException) -> None:
        if not _is_jit_arg_mismatch(err):
            raise err

        actual_sha = None
        try:
            actual_sha = _file_sha256(self._pkl_path)
        except OSError:
            pass

        if actual_sha and self._expected_sha256 and actual_sha != self._expected_sha256:
            try:
                os.remove(self._pkl_path)
            except OSError:
                pass
            redownload_msg = self._schedule_active_bundle_redownload()
            raise RuntimeError(
                "supercombo artifact runtime JIT mismatch with stale cached SHA: "
                f"expected {self._expected_sha256}, got {actual_sha} for {self._pkl_path}. "
                f"Deleted the stale cached file{redownload_msg}."
            ) from err

        raise RuntimeError(
            "supercombo artifact runtime JIT mismatch: "
            f"{err}. This model file does not match the current IQPilot runtime contract. "
            "Re-download or rebuild this model artifact."
        ) from err

    def _schedule_active_bundle_redownload(self) -> str:
        try:
            params = Params()
            active_bundle = params.get("ModelManager_ActiveBundle") or {}
            index = active_bundle.get("index") if isinstance(active_bundle, dict) else None
            if isinstance(index, str) and index.isdigit():
                index = int(index)
            if isinstance(index, int) and index >= 0:
                params.put("ModelManager_DownloadIndex", str(index))
                params.remove("ModelRunnerTypeCache")
                return "; scheduled automatic re-download of the active model"
        except Exception:
            pass

        return "; unable to schedule automatic re-download"

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
        try:
            warped = warp(tfm=self._queues['tfm'], big_tfm=self._queues['big_tfm'], frame=frame, big_frame=big_frame)
            out, = self._run_policy(warped=warped, img_q=self._queues['img_q'], big_img_q=self._queues['big_img_q'],
                                    feat_q=self._queues['feat_q'], desire_q=self._queues['desire_q'],
                                    packed_npy_inputs=self._queues['packed_npy_inputs'])
        except Exception as err:
            self._handle_runtime_jit_mismatch(err)
            raise
        flat = out.numpy().flatten()

        # feed hidden_state back as prev_feat for the next frame
        self._npy['prev_feat'][:] = flat[self._hidden_slice].reshape(self._npy['prev_feat'].shape)

        sliced = {k: flat[np.newaxis, sl] for k, sl in self._slices.items()}
        return self._parser.parse_vision_outputs(sliced)  # single-pass; parse_outputs double-parses a combined dict

    def _run_model(self) -> NumpyDict:
        raise RuntimeError("supercombo path goes through run_fused(), not _run_model()")
