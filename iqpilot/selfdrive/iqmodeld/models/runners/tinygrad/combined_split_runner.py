"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from openpilot.iqpilot.selfdrive.iqmodeld.models.combined_artifact import resolve_combined_split_artifact
from openpilot.iqpilot.selfdrive.iqmodeld.models.helpers import get_active_bundle
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import NumpyDict, ShapeDict, SliceDict
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import ModelRunner
from openpilot.iqpilot.selfdrive.iqmodeld.models.split_model_constants import SplitModelConstants
from openpilot.iqpilot.selfdrive.iqmodeld.parser import PhaseParser


def _tinygrad_imports():
  from tinygrad.device import Device
  from tinygrad.tensor import Tensor
  return Tensor, Device


def _phase_roles(meta_by_role: dict[str, dict]) -> list[str]:
  return [name for name in meta_by_role if name != "vision"]


def _phase_desire_key(policy_shapes: dict[str, tuple[int, ...]]) -> str:
  for key in policy_shapes:
    if key.startswith("desire"):
      return key
  raise KeyError("No desire-like key found in policy inputs")


def _phase_image_keys(vision_shapes: dict[str, tuple[int, ...]]) -> tuple[str, str]:
  names = sorted(name for name in vision_shapes if "img" in name)
  road_key = next((name for name in names if "big" not in name), None)
  wide_key = next((name for name in names if "big" in name), None)
  if road_key is None or wide_key is None:
    raise ValueError(f"Unable to resolve road/wide image keys from {list(vision_shapes)}")
  return road_key, wide_key


def _base_policy_keys(policy_shapes: dict[str, tuple[int, ...]]) -> set[str]:
  desired_key = _phase_desire_key(policy_shapes)
  return {desired_key, "features_buffer", "traffic_convention", "action_t"}


def _slice_map(raw_blob: np.ndarray, slices: dict[str, slice]) -> NumpyDict:
  return {name: raw_blob[np.newaxis, section] for name, section in slices.items() if name != "pad"}


class TinygradCombinedSplitRunner(ModelRunner):
  uses_opencl_warp: bool = False

  def __init__(self):
    super().__init__()
    self._constants = SplitModelConstants
    self._parser = PhaseParser()
    self._bundle = get_active_bundle()
    self._artifact_path = resolve_combined_split_artifact(self._bundle)
    if self._artifact_path is None:
      raise FileNotFoundError("No IQ combined split artifact is available for the active bundle")

    with open(self._artifact_path, "rb") as artifact:
      runtime_package: dict[Any, Any] = pickle.load(artifact)

    self._meta_by_role = runtime_package.get("meta_by_role", runtime_package.get("metadata", {}))
    self._policy_roles = runtime_package.get("roles", _phase_roles(self._meta_by_role))
    self._camera_programs = {
      camera_key: spec
      for camera_key, spec in runtime_package.items()
      if isinstance(camera_key, tuple) and isinstance(spec, dict)
    }
    self._execute_bundle = runtime_package.get("execute_bundle", runtime_package.get("run_policy"))
    self._frame_stride = int(runtime_package.get("frame_stride", runtime_package.get("frame_skip", 1)))

    if "vision" not in self._meta_by_role:
      raise ValueError("Combined split artifact is missing vision metadata")
    if not self._policy_roles:
      raise ValueError("Combined split artifact is missing policy roles")
    if self._execute_bundle is None:
      raise ValueError("Combined split artifact is missing execute_bundle")

    self._vision_meta = self._meta_by_role["vision"]
    self._primary_policy_meta = self._meta_by_role[self._policy_roles[0]]
    self._desired_key = _phase_desire_key(self._primary_policy_meta["input_shapes"])
    self._road_key, self._wide_key = _phase_image_keys(self._vision_meta["input_shapes"])
    self._extra_policy_keys = [
      key for key in self._primary_policy_meta["input_shapes"]
      if key not in _base_policy_keys(self._primary_policy_meta["input_shapes"])
    ]

    self._queue_tensors: dict[str, Any] | None = None
    self._numpy_state: dict[str, np.ndarray] | None = None
    self._camera_shape: tuple[int, int] | None = None
    self._blob_cache: dict[tuple[str, int], Any] = {}
    self._last_desire = np.zeros(self._primary_policy_meta["input_shapes"][self._desired_key][2], dtype=np.float32)

  @property
  def vision_input_names(self) -> list[str]:
    return [self._road_key, self._wide_key]

  @property
  def input_shapes(self) -> ShapeDict:
    merged: ShapeDict = dict(self._vision_meta["input_shapes"])
    for role in self._policy_roles:
      merged.update(self._meta_by_role[role]["input_shapes"])
    return merged

  @property
  def output_slices(self) -> SliceDict:
    merged: SliceDict = dict(self._vision_meta["output_slices"])
    for role in self._policy_roles:
      merged.update(self._meta_by_role[role]["output_slices"])
    return merged

  def prepare_inputs(self, imgs_cl, numpy_inputs, frames):
    raise RuntimeError("Combined split runner manages its own warp + queue state; use run_fused()")

  def _frame_blob(self, stream_name: str, buf):
    Tensor, Device = _tinygrad_imports()
    raw_frame = np.frombuffer(buf.data, dtype=np.uint8)
    cache_key = (stream_name, raw_frame.ctypes.data)
    tensor = self._blob_cache.get(cache_key)
    if tensor is None:
      tensor = Tensor.from_blob(raw_frame.ctypes.data, (raw_frame.size,), dtype="uint8", device=Device.DEFAULT)
      self._blob_cache[cache_key] = tensor
    return tensor

  def _allocate_runtime_state(self, camera_width: int, camera_height: int) -> None:
    if self._queue_tensors is not None and self._camera_shape == (camera_width, camera_height):
      return
    if (camera_width, camera_height) not in self._camera_programs:
      raise RuntimeError(f"No combined split kernels available for {camera_width}x{camera_height}")

    Tensor, Device = _tinygrad_imports()
    vision_shapes = self._vision_meta["input_shapes"]
    policy_shapes = self._primary_policy_meta["input_shapes"]

    image_shape = vision_shapes[self._road_key]
    frame_history = image_shape[1] // 6
    queue_depth = self._frame_stride * (frame_history - 1) + 1
    frame_queue_shape = (queue_depth, 6, image_shape[2], image_shape[3])

    feature_shape = policy_shapes["features_buffer"]
    desired_shape = policy_shapes[self._desired_key]
    traffic_shape = policy_shapes["traffic_convention"]
    action_shape = policy_shapes.get("action_t", traffic_shape)

    numpy_state = {
      "tfm": np.zeros((3, 3), dtype=np.float32),
      "big_tfm": np.zeros((3, 3), dtype=np.float32),
      "desire": np.zeros(desired_shape[2], dtype=np.float32),
      "traffic_convention": np.zeros(traffic_shape, dtype=np.float32),
      "action_t": np.zeros(action_shape, dtype=np.float32),
    }
    for key in self._extra_policy_keys:
      numpy_state[key] = np.zeros(policy_shapes[key], dtype=np.float32)

    queue_tensors = {
      "img_q": Tensor(np.zeros(frame_queue_shape, dtype=np.uint8), device=Device.DEFAULT).contiguous().realize(),
      "big_img_q": Tensor(np.zeros(frame_queue_shape, dtype=np.uint8), device=Device.DEFAULT).contiguous().realize(),
      "feat_q": Tensor(
        np.zeros((self._frame_stride * (feature_shape[1] - 1) + 1, feature_shape[0], feature_shape[2]), dtype=np.float32),
        device=Device.DEFAULT,
      ).contiguous().realize(),
      "desire_q": Tensor(
        np.zeros((self._frame_stride * desired_shape[1], desired_shape[0], desired_shape[2]), dtype=np.float32),
        device=Device.DEFAULT,
      ).contiguous().realize(),
      **{name: Tensor(value, device="NPY").realize() for name, value in numpy_state.items()},
    }

    self._queue_tensors = queue_tensors
    self._numpy_state = numpy_state
    self._camera_shape = (camera_width, camera_height)

  def _policy_inputs(self) -> dict[str, Any]:
    assert self._queue_tensors is not None
    tensor_names = ["feat_q", "desire_q", "desire", "traffic_convention", "action_t", *self._extra_policy_keys]
    return {name: self._queue_tensors[name] for name in tensor_names if name in self._queue_tensors}

  def _merge_policy_outputs(self, raw_outputs: tuple[Any, ...]) -> NumpyDict:
    outputs = self._parser.parse_vision_outputs(
      _slice_map(raw_outputs[0].numpy().flatten(), self._vision_meta["output_slices"])
    )

    has_on_policy = any(role == "on_policy" for role in self._policy_roles)
    for role_name, tensor_out in zip(self._policy_roles, raw_outputs[1:], strict=True):
      parsed = self._parser.parse_policy_outputs(
        _slice_map(tensor_out.numpy().flatten(), self._meta_by_role[role_name]["output_slices"])
      )
      if role_name == "off_policy" and has_on_policy:
        parsed.pop("plan", None)
      outputs.update(parsed)

    if "planplus" in outputs and "plan" in outputs:
      outputs["plan"] = outputs["plan"] + outputs["planplus"]
    return outputs

  def run_fused(self, bufs: dict, transforms: dict[str, np.ndarray], numpy_inputs: NumpyDict) -> NumpyDict:
    main_buf = bufs[self._road_key]
    self._allocate_runtime_state(main_buf.width, main_buf.height)
    assert self._queue_tensors is not None and self._numpy_state is not None and self._camera_shape is not None

    self._numpy_state["tfm"][:] = transforms[self._road_key]
    self._numpy_state["big_tfm"][:] = transforms[self._wide_key]

    current_desire = numpy_inputs[self._desired_key].copy()
    current_desire[0] = 0
    self._numpy_state["desire"][:] = np.where(current_desire - self._last_desire > 0.99, current_desire, 0)
    self._last_desire[:] = current_desire

    if "traffic_convention" in numpy_inputs:
      self._numpy_state["traffic_convention"][:] = numpy_inputs["traffic_convention"]
    if "action_t" in numpy_inputs:
      self._numpy_state["action_t"][:] = numpy_inputs["action_t"]
    for key in self._extra_policy_keys:
      if key in numpy_inputs:
        self._numpy_state[key][:] = numpy_inputs[key]

    stage_inputs = self._camera_programs[self._camera_shape].get("stage_inputs", self._camera_programs[self._camera_shape].get("warp_enqueue"))
    if stage_inputs is None:
      raise RuntimeError("Combined split artifact camera entry is missing stage_inputs")

    staged_main, staged_wide = stage_inputs(
      img_q=self._queue_tensors["img_q"],
      big_img_q=self._queue_tensors["big_img_q"],
      tfm=self._queue_tensors["tfm"],
      big_tfm=self._queue_tensors["big_tfm"],
      frame=self._frame_blob(self._road_key, bufs[self._road_key]),
      big_frame=self._frame_blob(self._wide_key, bufs[self._wide_key]),
    )
    raw_outputs = self._execute_bundle(img=staged_main, big_img=staged_wide, **self._policy_inputs())
    if not isinstance(raw_outputs, tuple):
      raw_outputs = (raw_outputs,)
    return self._merge_policy_outputs(raw_outputs)

  def _run_model(self) -> NumpyDict:
    raise RuntimeError("Combined split runner executes through run_fused()")
