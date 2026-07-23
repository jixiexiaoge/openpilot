"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from __future__ import annotations

import argparse
import atexit
import os
import pickle
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np


def _install_firmware_fetch_patch() -> None:
  import hashlib
  import pathlib

  import zstandard
  from tinygrad import helpers

  if not hasattr(helpers, "fetch_fw"):
    return

  original_fetch = helpers.fetch_fw

  def fetch_fw(path, name, sha256):
    archive_path = pathlib.Path(f"/lib/firmware/{path}/{name}.zst")
    if archive_path.is_file():
      blob = zstandard.ZstdDecompressor().stream_reader(archive_path.read_bytes()).read()
      if hashlib.sha256(blob).hexdigest() == sha256:
        return blob
    return original_fetch(path, name, sha256)

  helpers.fetch_fw = fetch_fw


_install_firmware_fetch_patch()

from tinygrad.device import Device
from tinygrad.engine.jit import TinyJit
from tinygrad.helpers import Context
from tinygrad.nn.onnx import OnnxRunner
from tinygrad.tensor import Tensor


@dataclass(frozen=True)
class FrameGeometry:
  width: int
  height: int
  stride: int
  y_height: int
  uv_height: int
  size: int


WARP_INPUT_NAMES = ["img_q", "big_img_q", "tfm", "big_tfm"]
POLICY_INPUT_NAMES = ["feat_q", "desire_q", "desire", "traffic_convention", "action_t"]
WARP_DEV = os.getenv("WARP_DEV")


def _random_tensor_inputs(keys: list[str], shape, device=None):
  return {key: Tensor.randint(shape, low=0, high=256, dtype="uint8", device=device).realize() for key in keys}


def _project_frame(src_flat, inverse_matrix, dst_shape, src_shape, stride_pad, border_fill_val=None):
  dst_w, dst_h = dst_shape
  src_h, src_w = src_shape

  x = Tensor.arange(dst_w, device=WARP_DEV).reshape(1, dst_w).expand(dst_h, dst_w).reshape(-1)
  y = Tensor.arange(dst_h, device=WARP_DEV).reshape(dst_h, 1).expand(dst_h, dst_w).reshape(-1)

  src_x = inverse_matrix[0, 0] * x + inverse_matrix[0, 1] * y + inverse_matrix[0, 2]
  src_y = inverse_matrix[1, 0] * x + inverse_matrix[1, 1] * y + inverse_matrix[1, 2]
  src_w_scale = inverse_matrix[2, 0] * x + inverse_matrix[2, 1] * y + inverse_matrix[2, 2]

  src_x = src_x / src_w_scale
  src_y = src_y / src_w_scale

  rounded_x = Tensor.round(src_x)
  rounded_y = Tensor.round(src_y)
  clipped_x = rounded_x.clip(0, src_w - 1).cast("int")
  clipped_y = rounded_y.clip(0, src_h - 1).cast("int")
  gather_index = clipped_y * (src_w + stride_pad) + clipped_x
  sampled = src_flat[gather_index]

  if border_fill_val is None:
    return sampled

  inside = ((rounded_x >= 0) & (rounded_x <= src_w - 1) & (rounded_y >= 0) & (rounded_y <= src_h - 1)).cast(sampled.dtype)
  return sampled * inside + Tensor(border_fill_val, dtype=sampled.dtype) * (1 - inside)


def _nv12_to_model_planes(yuv_frame):
  y_height = (yuv_frame.shape[0] * 2) // 3
  frame_width = yuv_frame.shape[1]
  return Tensor.cat(
    yuv_frame[0:y_height:2, 0::2],
    yuv_frame[1:y_height:2, 0::2],
    yuv_frame[0:y_height:2, 1::2],
    yuv_frame[1:y_height:2, 1::2],
    yuv_frame[y_height:y_height + y_height // 4].reshape((y_height // 2, frame_width // 2)),
    yuv_frame[y_height + y_height // 4:y_height + y_height // 2].reshape((y_height // 2, frame_width // 2)),
    dim=0,
  ).reshape((6, y_height // 2, frame_width // 2))


def _warp_kernel_factory(nv12: FrameGeometry, model_w: int, model_h: int):
  uv_offset = nv12.stride * nv12.y_height
  stride_pad = nv12.stride - nv12.width

  def prepare_frame(nv12_blob, inverse_matrix):
    inverse_uv = inverse_matrix * Tensor([[1.0, 1.0, 0.5], [1.0, 1.0, 0.5], [2.0, 2.0, 1.0]], device=WARP_DEV)
    uv_plane = nv12_blob[uv_offset:uv_offset + nv12.uv_height * nv12.stride].reshape(nv12.uv_height, nv12.stride)
    with Context(SPLIT_REDUCEOP=0):
      y_plane = _project_frame(nv12_blob[:nv12.height * nv12.stride], inverse_matrix, (model_w, model_h), (nv12.height, nv12.width), stride_pad).realize()
      u_plane = _project_frame(uv_plane[:nv12.height // 2, :nv12.width:2].flatten(), inverse_uv, (model_w // 2, model_h // 2), (nv12.height // 2, nv12.width // 2), 0).realize()
      v_plane = _project_frame(uv_plane[:nv12.height // 2, 1:nv12.width:2].flatten(), inverse_uv, (model_w // 2, model_h // 2), (nv12.height // 2, nv12.width // 2), 0).realize()
    return _nv12_to_model_planes(y_plane.cat(u_plane).cat(v_plane).reshape((model_h * 3 // 2, model_w)))

  return prepare_frame


def _vision_queue_state(vision_shapes, frame_skip, device):
  img_shape = vision_shapes["img"]
  frame_history = img_shape[1] // 6
  queue_shape = (frame_skip * (frame_history - 1) + 1, 6, img_shape[2], img_shape[3])
  numpy_state = {
    "tfm": np.zeros((3, 3), dtype=np.float32),
    "big_tfm": np.zeros((3, 3), dtype=np.float32),
  }
  tensor_state = {
    "img_q": Tensor(np.zeros(queue_shape, dtype=np.uint8), device=device).contiguous().realize(),
    "big_img_q": Tensor(np.zeros(queue_shape, dtype=np.uint8), device=device).contiguous().realize(),
    **{name: Tensor(value, device="NPY").realize() for name, value in numpy_state.items()},
  }
  return tensor_state, numpy_state


def _policy_queue_state(vision_shapes, policy_shapes, frame_skip, device):
  tensor_state, numpy_state = _vision_queue_state(vision_shapes, frame_skip, device)
  feature_shape = policy_shapes["features_buffer"]
  desire_shape = policy_shapes["desire_pulse"]
  traffic_shape = policy_shapes["traffic_convention"]
  action_shape = traffic_shape

  policy_numpy = {
    "desire": np.zeros(desire_shape[2], dtype=np.float32),
    "traffic_convention": np.zeros(traffic_shape, dtype=np.float32),
    "action_t": np.zeros(action_shape, dtype=np.float32),
  }
  numpy_state.update(policy_numpy)
  tensor_state.update({
    "feat_q": Tensor(np.zeros((frame_skip * (feature_shape[1] - 1) + 1, feature_shape[0], feature_shape[2]), dtype=np.float32), device=device).contiguous().realize(),
    "desire_q": Tensor(np.zeros((frame_skip * desire_shape[1], desire_shape[0], desire_shape[2]), dtype=np.float32), device=device).contiguous().realize(),
    **{name: Tensor(value, device="NPY").realize() for name, value in policy_numpy.items()},
  })
  return tensor_state, numpy_state


def _roll_queue(queue_tensor, incoming, sampler):
  queue_tensor.assign(queue_tensor[1:].cat(incoming, dim=0).contiguous())
  return sampler(queue_tensor)


def _sample_sparse(queue_tensor, frame_skip):
  return queue_tensor[::frame_skip].contiguous().flatten(0, 1).unsqueeze(0)


def _sample_desire(queue_tensor, frame_skip):
  return queue_tensor.reshape(-1, frame_skip, *queue_tensor.shape[1:]).max(1).flatten(0, 1).unsqueeze(0)


def _build_warp_enqueuer(nv12: FrameGeometry, model_w: int, model_h: int, frame_skip: int):
  prepare_frame = _warp_kernel_factory(nv12, model_w, model_h)
  sparse_sampler = partial(_sample_sparse, frame_skip=frame_skip)

  def enqueue(img_q, big_img_q, tfm, big_tfm, frame, big_frame):
    tfm = tfm.to(WARP_DEV)
    big_tfm = big_tfm.to(WARP_DEV)
    Tensor.realize(tfm, big_tfm)

    warped_main = prepare_frame(frame, tfm).unsqueeze(0).to(Device.DEFAULT)
    warped_big = prepare_frame(big_frame, big_tfm).unsqueeze(0).to(Device.DEFAULT)
    return (
      _roll_queue(img_q, warped_main, sparse_sampler),
      _roll_queue(big_img_q, warped_big, sparse_sampler),
    )

  return enqueue


def _policy_executor(model_runners, model_metadata, frame_skip):
  desire_sampler = partial(_sample_desire, frame_skip=frame_skip)
  sparse_sampler = partial(_sample_sparse, frame_skip=frame_skip)
  hidden_slice = model_metadata["vision"]["output_slices"]["hidden_state"]

  def execute(img, big_img, feat_q, desire_q, desire, traffic_convention, action_t):
    desire = desire.to(Device.DEFAULT)
    traffic_convention = traffic_convention.to(Device.DEFAULT)
    action_t = action_t.to(Device.DEFAULT)
    Tensor.realize(desire, traffic_convention, action_t)

    desire_buffer = _roll_queue(desire_q, desire.reshape(1, 1, -1), desire_sampler)
    vision_output = next(iter(model_runners["vision"]({"img": img, "big_img": big_img}).values())).cast("float32")

    hidden_state = vision_output[:, hidden_slice].reshape(1, -1).unsqueeze(0)
    feature_buffer = _roll_queue(feat_q, hidden_state, sparse_sampler)

    on_inputs = {
      "features_buffer": feature_buffer,
      "desire_pulse": desire_buffer,
      "traffic_convention": traffic_convention,
      "action_t": action_t,
    }
    on_output = next(iter(model_runners["on_policy"](on_inputs).values())).cast("float32")
    off_output = next(iter(model_runners["off_policy"](on_inputs).values())).cast("float32")
    return vision_output, on_output, off_output

  return execute


def _replay_and_freeze(jit_runner, random_inputs_factory, queue_keys, queue_factory):
  seed = 42

  def validate(fn, seed_value, baseline_output=None, baseline_buffers=None, expect_match=True):
    queue_tensors, numpy_values = queue_factory(Device.DEFAULT)
    np.random.seed(seed_value)
    Tensor.manual_seed(seed_value)

    replay_count = 1 if (baseline_output is not None or baseline_buffers is not None) else 3
    for run_index in range(replay_count):
      for value in numpy_values.values():
        value[:] = np.random.randn(*value.shape).astype(value.dtype)
      Device.default.synchronize()
      random_inputs = random_inputs_factory()
      start = time.perf_counter()
      outputs = fn(**{key: queue_tensors[key] for key in queue_keys}, **random_inputs)
      enqueue_done = time.perf_counter()
      Device.default.synchronize()
      total_done = time.perf_counter()
      print(f"  [{run_index + 1}/{replay_count}] enqueue {(enqueue_done - start) * 1e3:6.2f} ms -- total {(total_done - start) * 1e3:6.2f} ms")

      if run_index == 0:
        output_snapshot = [np.copy(value.numpy()) for value in outputs]
        buffer_snapshot = [np.copy(value.numpy().copy()) for value in queue_tensors.values()]

    if baseline_output is not None:
      matches = all(np.array_equal(current, reference) for current, reference in zip(output_snapshot, baseline_output, strict=True))
      assert matches == expect_match, f"outputs {'differ from' if expect_match else 'match'} baseline (seed={seed_value})"
    if baseline_buffers is not None:
      matches = all(np.array_equal(current, reference) for current, reference in zip(buffer_snapshot, baseline_buffers, strict=True))
      assert matches == expect_match, f"buffers {'differ from' if expect_match else 'match'} baseline (seed={seed_value})"
    return output_snapshot, buffer_snapshot

  print("capture + replay")
  first_output, first_buffers = validate(jit_runner, seed)
  print("pickle round trip")
  frozen = pickle.loads(pickle.dumps(jit_runner))
  validate(frozen, seed, first_output, first_buffers, expect_match=True)
  validate(frozen, seed + 1, first_output, first_buffers, expect_match=False)
  return frozen


def _parse_size(text: str) -> tuple[int, int]:
  width, height = text.lower().split("x")
  return int(width), int(height)


def _read_file_to_shared_memory(path: str) -> str:
  from openpilot.common.file_chunker import read_file_chunked
  from openpilot.system.hardware.hw import Paths

  shm_path = os.path.join(Paths.shm_path(), os.path.basename(path))
  atexit.register(lambda: os.path.exists(shm_path) and os.remove(shm_path))
  with open(shm_path, "wb") as handle:
    handle.write(read_file_chunked(path))
  return shm_path


def _arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser()
  parser.add_argument("--model-size", type=_parse_size, required=True, help="model input WxH")
  parser.add_argument("--camera-resolutions", type=_parse_size, nargs="+", required=True, help="camera resolutions WxH (one or more)")
  parser.add_argument("--vision-onnx", required=True)
  parser.add_argument("--off-policy-onnx", required=True)
  parser.add_argument("--on-policy-onnx", required=True)
  parser.add_argument("--output", required=True)
  parser.add_argument("--frame-skip", type=int, required=True)
  return parser


def main(argv: list[str] | None = None) -> int:
  from openpilot.iqpilot.selfdrive.iqmodeld.metadata import build_metadata_record
  from openpilot.system.camerad.cameras.nv12_info import get_nv12_info

  args = _arg_parser().parse_args(argv)
  model_w, model_h = args.model_size

  model_paths = {
    "vision": _read_file_to_shared_memory(args.vision_onnx),
    "off_policy": _read_file_to_shared_memory(args.off_policy_onnx),
    "on_policy": _read_file_to_shared_memory(args.on_policy_onnx),
  }
  model_runners = {name: OnnxRunner(path) for name, path in model_paths.items()}
  metadata = {name: build_metadata_record(path) for name, path in model_paths.items()}

  assert metadata["off_policy"]["input_shapes"] == metadata["on_policy"]["input_shapes"]

  output_package: dict = {"metadata": metadata}
  policy_jit = TinyJit(_policy_executor(model_runners, metadata, args.frame_skip), prune=True)
  policy_queue_factory = partial(_policy_queue_state, metadata["vision"]["input_shapes"], metadata["on_policy"]["input_shapes"], args.frame_skip)
  random_model_inputs = partial(_random_tensor_inputs, keys=["img", "big_img"], shape=metadata["vision"]["input_shapes"]["img"])
  output_package["run_policy"] = _replay_and_freeze(policy_jit, random_model_inputs, POLICY_INPUT_NAMES, policy_queue_factory)

  for cam_w, cam_h in args.camera_resolutions:
    nv12 = FrameGeometry(cam_w, cam_h, *get_nv12_info(cam_w, cam_h))
    warp_jit = TinyJit(_build_warp_enqueuer(nv12, model_w, model_h, args.frame_skip), prune=True)
    warp_queue_factory = partial(_vision_queue_state, metadata["vision"]["input_shapes"], args.frame_skip)
    random_warp_inputs = partial(_random_tensor_inputs, keys=["frame", "big_frame"], shape=nv12.size, device=WARP_DEV)
    output_package[(cam_w, cam_h)] = _replay_and_freeze(warp_jit, random_warp_inputs, WARP_INPUT_NAMES, warp_queue_factory)

  output_package["frame_skip"] = args.frame_skip
  with open(args.output, "wb") as handle:
    pickle.dump(output_package, handle)
  print(f"Saved JITs to {args.output} ({os.path.getsize(args.output) / 1e6:.2f} MB)")
  return 0
