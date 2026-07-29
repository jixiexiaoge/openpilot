"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass

import numpy as np
from tinygrad.tensor import Tensor

from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import (
  CLMemDict,
  CUSTOM_MODEL_PATH,
  FrameDict,
  ModelType,
  NumpyDict,
  ShapeDict,
  SliceDict,
)
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import ModelRunner
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.tinygrad.model_types import (
  OffPolicyTinygrad,
  OnPolicyTinygrad,
  PolicyTinygrad,
  SupercomboTinygrad,
  VisionTinygrad,
)
from openpilot.iqpilot.selfdrive.iqmodeld.models.split_model_constants import SplitModelConstants
from openpilot.iqpilot.selfdrive.iqmodeld.config import ModelConstants
from openpilot.iqpilot.selfdrive.iqmodeld.runtime.tinygrad import qcom_tensor_from_opencl_address
from openpilot.system.hardware import TICI


@dataclass(frozen=True)
class _TensorShapePlan:
  dtype: object
  device: str


def _artifact_path(filename: str) -> str:
  return f"{CUSTOM_MODEL_PATH}/{filename}"


def _load_program_blob(filename: str):
  with open(_artifact_path(filename), "rb") as artifact:
    try:
      return pickle.load(artifact)
    except FileNotFoundError as exc:
      assert "/dev/kgsl-3d0" not in str(exc), "Model was built on C3 or C3X, but is being loaded on PC"
      raise


def _compile_input_plan(captured) -> dict[str, _TensorShapePlan]:
  plan: dict[str, _TensorShapePlan] = {}
  for name, info in zip(captured.expected_names, captured.expected_input_info, strict=True):
    plan[name] = _TensorShapePlan(dtype=info[2], device=info[3])
  return plan


def _merge_step_outputs(output_groups: list[NumpyDict]) -> NumpyDict:
  stitched: NumpyDict = {}
  for payload in output_groups:
    stitched.update(payload)
  if "planplus" in stitched and "plan" in stitched:
    stitched["plan"] = stitched["plan"] + stitched["planplus"]
  return stitched


class TinygradRunner(ModelRunner, SupercomboTinygrad, PolicyTinygrad, VisionTinygrad, OffPolicyTinygrad, OnPolicyTinygrad):
  def __init__(self, model_type: int = ModelType.supercombo):
    ModelRunner.__init__(self)
    for initializer in (SupercomboTinygrad, PolicyTinygrad, VisionTinygrad, OffPolicyTinygrad, OnPolicyTinygrad):
      initializer.__init__(self)

    self._constants = ModelConstants
    self._model_data = self.models.get(model_type)
    if self._model_data is None or self._model_data.model is None:
      raise ValueError(f"Model data for type {model_type} not available.")

    asset_name = self._model_data.model.artifact.fileName
    assert asset_name.endswith("_tinygrad.pkl"), f"Invalid model file {asset_name} for TinygradRunner"

    self.model_run = _load_program_blob(asset_name)
    self._input_plan = _compile_input_plan(self.model_run.captured)
    self.input_to_dtype = {name: spec.dtype for name, spec in self._input_plan.items()}
    self.input_to_device = {name: spec.device for name, spec in self._input_plan.items()}

  @property
  def vision_input_names(self) -> list[str]:
    return [stream_name for stream_name in self.input_shapes if "img" in stream_name]

  def _attach_vision_tensor(self, stream_name: str, frame_buffers: CLMemDict, frame_views: FrameDict) -> None:
    spec = self._input_plan[stream_name]
    frame_buffer = frame_buffers[stream_name]
    if TICI:
      self.inputs[stream_name] = qcom_tensor_from_opencl_address(frame_buffer.mem_address,
                                                                 self.input_shapes[stream_name],
                                                                 dtype=spec.dtype)
      return

    mirrored = frame_views[stream_name].as_numpy(frame_buffer).reshape(self.input_shapes[stream_name])
    self.inputs[stream_name] = Tensor(mirrored, device=spec.device, dtype=spec.dtype).realize()

  def _attach_state_tensor(self, tensor_name: str, tensor_value: np.ndarray) -> None:
    spec = self._input_plan[tensor_name]
    self.inputs[tensor_name] = Tensor(tensor_value, device=spec.device, dtype=spec.dtype).realize()

  def prepare_vision_inputs(self, imgs_cl: CLMemDict, frames: FrameDict):
    for stream_name in imgs_cl:
      if stream_name not in self.inputs or not TICI:
        self._attach_vision_tensor(stream_name, imgs_cl, frames)

  def prepare_policy_inputs(self, numpy_inputs: NumpyDict):
    for tensor_name, tensor_value in numpy_inputs.items():
      self._attach_state_tensor(tensor_name, tensor_value)

  def prepare_inputs(self, imgs_cl: CLMemDict, numpy_inputs: NumpyDict, frames: FrameDict) -> dict:
    self.prepare_vision_inputs(imgs_cl, frames)
    self.prepare_policy_inputs(numpy_inputs)
    return self.inputs

  def _parse_outputs(self, model_outputs: np.ndarray) -> NumpyDict:
    if self._model_data is None:
      raise ValueError("Model data is not available. Ensure the model is loaded correctly.")
    return self.parser_method_dict[self._model_data.model.type.raw](model_outputs)

  def _run_model(self) -> NumpyDict:
    raw_output = self.model_run(**self.inputs).numpy().reshape(-1)
    return self._parse_outputs(raw_output)


class TinygradSplitRunner(ModelRunner):
  def __init__(self):
    super().__init__()
    self.is_20hz_3d = True
    self._constants = SplitModelConstants
    self.vision_runner = TinygradRunner(ModelType.vision)
    self.policy_runner = TinygradRunner(ModelType.policy) if self.models.get(ModelType.policy) else None
    self.off_policy_runner = TinygradRunner(ModelType.offPolicy) if self.models.get(ModelType.offPolicy) else None
    self.on_policy_runner = TinygradRunner(ModelType.onPolicy) if self.models.get(ModelType.onPolicy) else None

  def _policy_units(self) -> list[TinygradRunner]:
    return [runner for runner in (self.policy_runner, self.off_policy_runner, self.on_policy_runner) if runner is not None]

  def run_vision(self) -> NumpyDict:
    return self.vision_runner.run_model()

  def run_policy(self) -> NumpyDict:
    return _merge_step_outputs([runner.run_model() for runner in self._policy_units()])

  def refresh_policy_features(self, features_buffer: np.ndarray) -> None:
    for runner in self._policy_units():
      if "features_buffer" in runner._input_plan:
        runner._attach_state_tensor("features_buffer", features_buffer)

  def _run_model(self) -> NumpyDict:
    return _merge_step_outputs([self.run_vision(), self.run_policy()])

  @property
  def vision_input_names(self) -> list[str]:
    return list(self.vision_runner.vision_input_names)

  @property
  def input_shapes(self) -> ShapeDict:
    composite: ShapeDict = dict(self.vision_runner.input_shapes)
    for runner in self._policy_units():
      composite.update(runner.input_shapes)
    return composite

  @property
  def output_slices(self) -> SliceDict:
    composite: SliceDict = dict(self.vision_runner.output_slices)
    for runner in self._policy_units():
      composite.update(runner.output_slices)
    return composite

  def prepare_inputs(self, imgs_cl: CLMemDict, numpy_inputs: NumpyDict, frames: FrameDict) -> dict:
    self.vision_runner.prepare_vision_inputs(imgs_cl, frames)
    assembled_inputs = dict(self.vision_runner.inputs)
    for runner in self._policy_units():
      runner.prepare_policy_inputs(numpy_inputs)
      assembled_inputs.update(runner.inputs)
    self.inputs = assembled_inputs
    return assembled_inputs
