#!/usr/bin/env python3
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

import numpy as np


def _patch_firmware_fetch() -> None:
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


_patch_firmware_fetch()

from tinygrad.device import Device
from tinygrad.engine.jit import TinyJit
from tinygrad.helpers import Context
from tinygrad.nn.onnx import OnnxRunner
from tinygrad.tensor import Tensor


@dataclass(frozen=True)
class CameraGeometry:
  width: int
  height: int
  stride: int
  y_height: int
  uv_height: int
  size: int


WARP_DEVICE = os.getenv("WARP_DEV")


def _read_shared_copy(path: str) -> str:
  from openpilot.common.file_chunker import read_file_chunked
  from openpilot.system.hardware.hw import Paths

  shm_path = os.path.join(Paths.shm_path(), os.path.basename(path))
  atexit.register(lambda: os.path.exists(shm_path) and os.remove(shm_path))
  with open(shm_path, "wb") as handle:
    handle.write(read_file_chunked(path))
  return shm_path


def _parse_size(text: str) -> tuple[int, int]:
  width, height = text.lower().split("x")
  return int(width), int(height)


def _rand_u8_inputs(keys: list[str], shape, device=None):
  return {key: Tensor.randint(shape, low=0, high=256, dtype="uint8", device=device).realize() for key in keys}


def _phase_desire_key(policy_shapes: dict[str, tuple[int, ...]]) -> str:
  for key in policy_shapes:
    if key.startswith("desire"):
      return key
  raise KeyError("No desire-like key found in policy shapes")


def _phase_image_keys(vision_shapes: dict[str, tuple[int, ...]]) -> tuple[str, str]:
  names = sorted(name for name in vision_shapes if "img" in name)
  road_key = next((name for name in names if "big" not in name), None)
  wide_key = next((name for name in names if "big" in name), None)
  if road_key is None or wide_key is None:
    raise ValueError(f"Unable to resolve road/wide image keys from {list(vision_shapes)}")
  return road_key, wide_key


def _base_policy_keys(policy_shapes: dict[str, tuple[int, ...]]) -> set[str]:
  return {
    _phase_desire_key(policy_shapes),
    "features_buffer",
    "traffic_convention",
    "action_t",
  }


def _common_policy_shapes(role_shapes: dict[str, dict[str, tuple[int, ...]]]) -> dict[str, tuple[int, ...]]:
  first_role = next(iter(role_shapes))
  baseline = role_shapes[first_role]
  for role_name, shape_map in role_shapes.items():
    if shape_map != baseline:
      raise ValueError(f"Policy input shapes differ for role {role_name}")
  return baseline


def _phase_frame_skip(policy_shapes: dict[str, tuple[int, ...]]) -> int:
  feature_shape = policy_shapes.get("features_buffer")
  if feature_shape is None:
    return 1
  history_length = feature_shape[1]
  return 1 if history_length >= 99 else 4


def _project_pixels(src_flat, inverse_matrix, dst_shape, src_shape, stride_pad, border_fill_val=None):
  dst_w, dst_h = dst_shape
  src_h, src_w = src_shape

  x_coords = Tensor.arange(dst_w, device=WARP_DEVICE).reshape(1, dst_w).expand(dst_h, dst_w).reshape(-1)
  y_coords = Tensor.arange(dst_h, device=WARP_DEVICE).reshape(dst_h, 1).expand(dst_h, dst_w).reshape(-1)

  src_x = inverse_matrix[0, 0] * x_coords + inverse_matrix[0, 1] * y_coords + inverse_matrix[0, 2]
  src_y = inverse_matrix[1, 0] * x_coords + inverse_matrix[1, 1] * y_coords + inverse_matrix[1, 2]
  scale = inverse_matrix[2, 0] * x_coords + inverse_matrix[2, 1] * y_coords + inverse_matrix[2, 2]

  src_x = src_x / scale
  src_y = src_y / scale

  rounded_x = Tensor.round(src_x)
  rounded_y = Tensor.round(src_y)
  gather_x = rounded_x.clip(0, src_w - 1).cast("int")
  gather_y = rounded_y.clip(0, src_h - 1).cast("int")
  gather_index = gather_y * (src_w + stride_pad) + gather_x
  sampled = src_flat[gather_index]

  if border_fill_val is None:
    return sampled

  inside = ((rounded_x >= 0) & (rounded_x <= src_w - 1) & (rounded_y >= 0) & (rounded_y <= src_h - 1)).cast(sampled.dtype)
  return sampled * inside + Tensor(border_fill_val, dtype=sampled.dtype) * (1 - inside)


def _pack_nv12_planes(stacked_frame):
  y_height = (stacked_frame.shape[0] * 2) // 3
  frame_width = stacked_frame.shape[1]
  return Tensor.cat(
    stacked_frame[0:y_height:2, 0::2],
    stacked_frame[1:y_height:2, 0::2],
    stacked_frame[0:y_height:2, 1::2],
    stacked_frame[1:y_height:2, 1::2],
    stacked_frame[y_height:y_height + y_height // 4].reshape((y_height // 2, frame_width // 2)),
    stacked_frame[y_height + y_height // 4:y_height + y_height // 2].reshape((y_height // 2, frame_width // 2)),
    dim=0,
  ).reshape((6, y_height // 2, frame_width // 2))


def _warp_program(camera: CameraGeometry, model_w: int, model_h: int):
  uv_offset = camera.stride * camera.y_height
  stride_pad = camera.stride - camera.width

  def prepare_frame(nv12_blob, inverse_matrix):
    uv_matrix = inverse_matrix * Tensor([[1.0, 1.0, 0.5], [1.0, 1.0, 0.5], [2.0, 2.0, 1.0]], device=WARP_DEVICE)
    uv_plane = nv12_blob[uv_offset:uv_offset + camera.uv_height * camera.stride].reshape(camera.uv_height, camera.stride)
    with Context(SPLIT_REDUCEOP=0):
      y_plane = _project_pixels(nv12_blob[:camera.height * camera.stride], inverse_matrix, (model_w, model_h), (camera.height, camera.width), stride_pad).realize()
      u_plane = _project_pixels(uv_plane[:camera.height // 2, :camera.width:2].flatten(), uv_matrix, (model_w // 2, model_h // 2), (camera.height // 2, camera.width // 2), 0).realize()
      v_plane = _project_pixels(uv_plane[:camera.height // 2, 1:camera.width:2].flatten(), uv_matrix, (model_w // 2, model_h // 2), (camera.height // 2, camera.width // 2), 0).realize()
    return _pack_nv12_planes(y_plane.cat(u_plane).cat(v_plane).reshape((model_h * 3 // 2, model_w)))

  return prepare_frame


def _sample_sparse(queue_tensor, frame_stride):
  return queue_tensor[::frame_stride].contiguous().flatten(0, 1).unsqueeze(0)


def _sample_desire(queue_tensor, frame_stride):
  return queue_tensor.reshape(-1, frame_stride, *queue_tensor.shape[1:]).max(1).flatten(0, 1).unsqueeze(0)


def _roll_queue(queue_tensor, incoming, sampler):
  queue_tensor.assign(queue_tensor[1:].cat(incoming, dim=0).contiguous())
  return sampler(queue_tensor)


def _vision_queue_buffers(vision_shapes: dict[str, tuple[int, ...]], frame_stride: int, device):
  road_key, _ = _phase_image_keys(vision_shapes)
  image_shape = vision_shapes[road_key]
  frame_history = image_shape[1] // 6
  queue_depth = frame_stride * (frame_history - 1) + 1
  frame_queue_shape = (queue_depth, 6, image_shape[2], image_shape[3])

  numpy_state = {
    "tfm": np.zeros((3, 3), dtype=np.float32),
    "big_tfm": np.zeros((3, 3), dtype=np.float32),
  }
  tensor_state = {
    "img_q": Tensor(np.zeros(frame_queue_shape, dtype=np.uint8), device=device).contiguous().realize(),
    "big_img_q": Tensor(np.zeros(frame_queue_shape, dtype=np.uint8), device=device).contiguous().realize(),
    **{name: Tensor(value, device="NPY").realize() for name, value in numpy_state.items()},
  }
  return tensor_state, numpy_state


def _policy_queue_buffers(vision_shapes: dict[str, tuple[int, ...]], policy_shapes: dict[str, tuple[int, ...]], frame_stride: int, device):
  tensor_state, numpy_state = _vision_queue_buffers(vision_shapes, frame_stride, device)
  desired_key = _phase_desire_key(policy_shapes)
  feature_shape = policy_shapes["features_buffer"]
  desired_shape = policy_shapes[desired_key]
  traffic_shape = policy_shapes["traffic_convention"]
  action_shape = policy_shapes.get("action_t", traffic_shape)

  numpy_policy = {
    "desire": np.zeros(desired_shape[2], dtype=np.float32),
    "traffic_convention": np.zeros(traffic_shape, dtype=np.float32),
    "action_t": np.zeros(action_shape, dtype=np.float32),
  }
  for key, shape in policy_shapes.items():
    if key not in _base_policy_keys(policy_shapes):
      numpy_policy[key] = np.zeros(shape, dtype=np.float32)

  numpy_state.update(numpy_policy)
  tensor_state.update({
    "feat_q": Tensor(np.zeros((frame_stride * (feature_shape[1] - 1) + 1, feature_shape[0], feature_shape[2]), dtype=np.float32), device=device).contiguous().realize(),
    "desire_q": Tensor(np.zeros((frame_stride * desired_shape[1], desired_shape[0], desired_shape[2]), dtype=np.float32), device=device).contiguous().realize(),
    **{name: Tensor(value, device="NPY").realize() for name, value in numpy_policy.items()},
  })
  return tensor_state, numpy_state


def _stage_program(camera: CameraGeometry, model_w: int, model_h: int, frame_stride: int):
  prepare_frame = _warp_program(camera, model_w, model_h)
  sparse_sampler = partial(_sample_sparse, frame_stride=frame_stride)

  def stage_inputs(img_q, big_img_q, tfm, big_tfm, frame, big_frame):
    tfm = tfm.to(WARP_DEVICE)
    big_tfm = big_tfm.to(WARP_DEVICE)
    Tensor.realize(tfm, big_tfm)
    staged_main = prepare_frame(frame, tfm).unsqueeze(0).to(Device.DEFAULT)
    staged_wide = prepare_frame(big_frame, big_tfm).unsqueeze(0).to(Device.DEFAULT)
    return (
      _roll_queue(img_q, staged_main, sparse_sampler),
      _roll_queue(big_img_q, staged_wide, sparse_sampler),
    )

  return stage_inputs


def _role_executor(model_runners: dict[str, OnnxRunner], meta_by_role: dict[str, dict], frame_stride: int):
  desired_sampler = partial(_sample_desire, frame_stride=frame_stride)
  sparse_sampler = partial(_sample_sparse, frame_stride=frame_stride)
  vision_hidden_slice = meta_by_role["vision"]["output_slices"]["hidden_state"]
  policy_roles = [name for name in meta_by_role if name != "vision"]
  policy_shapes = _common_policy_shapes({name: meta_by_role[name]["input_shapes"] for name in policy_roles})
  desired_key = _phase_desire_key(policy_shapes)
  road_key, wide_key = _phase_image_keys(meta_by_role["vision"]["input_shapes"])
  extra_keys = [key for key in policy_shapes if key not in _base_policy_keys(policy_shapes)]

  def execute_bundle(img, big_img, feat_q, desire_q, desire, traffic_convention, action_t, **extra):
    desired_tensor = desire.to(Device.DEFAULT)
    traffic_tensor = traffic_convention.to(Device.DEFAULT)
    action_tensor = action_t.to(Device.DEFAULT)
    extra_tensors = {key: extra[key].to(Device.DEFAULT) for key in extra_keys if key in extra}
    Tensor.realize(desired_tensor, traffic_tensor, action_tensor, *extra_tensors.values())

    desire_buffer = _roll_queue(desire_q, desired_tensor.reshape(1, 1, -1), desired_sampler)
    vision_output = next(iter(model_runners["vision"]({road_key: img, wide_key: big_img}).values())).cast("float32")
    hidden_state = vision_output[:, vision_hidden_slice].reshape(1, -1).unsqueeze(0)
    feature_buffer = _roll_queue(feat_q, hidden_state, sparse_sampler)

    common_inputs = {
      "features_buffer": feature_buffer,
      desired_key: desire_buffer,
      "traffic_convention": traffic_tensor,
      "action_t": action_tensor,
      **extra_tensors,
    }

    role_outputs = []
    for role_name in policy_roles:
      role_outputs.append(next(iter(model_runners[role_name](common_inputs).values())).cast("float32"))
    return (vision_output, *role_outputs)

  return execute_bundle


def _capture_and_freeze(jit_runner, random_inputs_factory, queue_keys, queue_factory):
  seed_value = 42

  def validate(fn, baseline_outputs=None, baseline_buffers=None, expect_match=True, replay_seed=seed_value):
    queue_tensors, numpy_values = queue_factory(Device.DEFAULT)
    np.random.seed(replay_seed)
    Tensor.manual_seed(replay_seed)

    replay_count = 1 if (baseline_outputs is not None or baseline_buffers is not None) else 3
    for pass_index in range(replay_count):
      for value in numpy_values.values():
        value[:] = np.random.randn(*value.shape).astype(value.dtype)
      Device.default.synchronize()
      random_inputs = random_inputs_factory()
      start_time = time.perf_counter()
      outputs = fn(**{name: queue_tensors[name] for name in queue_keys}, **random_inputs)
      enqueue_time = time.perf_counter()
      Device.default.synchronize()
      total_time = time.perf_counter()
      print(f"  [{pass_index + 1}/{replay_count}] enqueue {(enqueue_time - start_time) * 1e3:6.2f} ms -- total {(total_time - start_time) * 1e3:6.2f} ms")

      if pass_index == 0:
        output_snapshot = [np.copy(value.numpy()) for value in outputs]
        buffer_snapshot = [np.copy(value.numpy().copy()) for value in queue_tensors.values()]

    if baseline_outputs is not None:
      matches = all(np.array_equal(current, reference) for current, reference in zip(output_snapshot, baseline_outputs, strict=True))
      assert matches == expect_match, f"outputs {'differ from' if expect_match else 'match'} baseline"
    if baseline_buffers is not None:
      matches = all(np.array_equal(current, reference) for current, reference in zip(buffer_snapshot, baseline_buffers, strict=True))
      assert matches == expect_match, f"buffers {'differ from' if expect_match else 'match'} baseline"

    return output_snapshot, buffer_snapshot

  print("capture + replay")
  baseline_outputs, baseline_buffers = validate(jit_runner)
  print("pickle round trip")
  frozen = pickle.loads(pickle.dumps(jit_runner))
  validate(frozen, baseline_outputs, baseline_buffers, expect_match=True)
  validate(frozen, baseline_outputs, baseline_buffers, expect_match=False, replay_seed=seed_value + 1)
  return frozen


def _arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser()
  parser.add_argument("--model-size", type=_parse_size, required=True, help="model input WxH")
  parser.add_argument("--camera-resolutions", type=_parse_size, nargs="+", required=True, help="camera resolutions WxH")
  parser.add_argument("--vision-onnx", required=True)
  parser.add_argument("--policy-onnx")
  parser.add_argument("--off-policy-onnx")
  parser.add_argument("--on-policy-onnx")
  parser.add_argument("--output", required=True)
  parser.add_argument("--frame-skip", type=int)
  return parser


def main(argv: list[str] | None = None) -> int:
  from openpilot.iqpilot.selfdrive.iqmodeld.metadata import build_metadata_record
  from openpilot.system.camerad.cameras.nv12_info import get_nv12_info

  args = _arg_parser().parse_args(argv)
  model_w, model_h = args.model_size

  policy_specs = [
    ("policy", args.policy_onnx),
    ("off_policy", args.off_policy_onnx),
    ("on_policy", args.on_policy_onnx),
  ]
  active_policy_specs = [(role, path) for role, path in policy_specs if path]
  if not active_policy_specs:
    raise SystemExit("At least one policy ONNX must be provided")

  model_paths = {"vision": _read_shared_copy(args.vision_onnx)}
  for role_name, onnx_path in active_policy_specs:
    model_paths[role_name] = _read_shared_copy(onnx_path)

  model_runners = {role_name: OnnxRunner(path) for role_name, path in model_paths.items()}
  meta_by_role = {role_name: build_metadata_record(path) for role_name, path in model_paths.items()}

  shared_policy_shapes = _common_policy_shapes({
    role_name: meta_by_role[role_name]["input_shapes"] for role_name, _ in active_policy_specs
  })
  frame_stride = args.frame_skip if args.frame_skip is not None else _phase_frame_skip(shared_policy_shapes)

  package: dict[Any, Any] = {
    "meta_by_role": meta_by_role,
    "roles": [role_name for role_name, _ in active_policy_specs],
    "frame_stride": frame_stride,
  }

  executor_jit = TinyJit(_role_executor(model_runners, meta_by_role, frame_stride), prune=True)
  queue_factory = partial(_policy_queue_buffers, meta_by_role["vision"]["input_shapes"], shared_policy_shapes, frame_stride)
  image_shape = meta_by_role["vision"]["input_shapes"][_phase_image_keys(meta_by_role["vision"]["input_shapes"])[0]]
  package["execute_bundle"] = _capture_and_freeze(
    executor_jit,
    partial(_rand_u8_inputs, keys=["img", "big_img"], shape=image_shape),
    ["feat_q", "desire_q", "desire", "traffic_convention", "action_t", *[k for k in shared_policy_shapes if k not in _base_policy_keys(shared_policy_shapes)]],
    queue_factory,
  )

  for camera_width, camera_height in args.camera_resolutions:
    camera = CameraGeometry(camera_width, camera_height, *get_nv12_info(camera_width, camera_height))
    stage_jit = TinyJit(_stage_program(camera, model_w, model_h, frame_stride), prune=True)
    package[(camera_width, camera_height)] = {
      "stage_inputs": _capture_and_freeze(
        stage_jit,
        partial(_rand_u8_inputs, keys=["frame", "big_frame"], shape=camera.size, device=WARP_DEVICE),
        ["img_q", "big_img_q", "tfm", "big_tfm"],
        partial(_vision_queue_buffers, meta_by_role["vision"]["input_shapes"], frame_stride),
      )
    }

  with open(args.output, "wb") as handle:
    pickle.dump(package, handle)
  print(f"Saved combined split runtime to {args.output} ({os.path.getsize(args.output) / 1e6:.2f} MB)")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
