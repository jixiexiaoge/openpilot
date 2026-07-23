"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from __future__ import annotations

import numpy as np

from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import CLMemDict, FrameDict, ModelType, NumpyDict, ShapeDict
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import ModelRunner
from openpilot.iqpilot.selfdrive.iqmodeld import MODEL_PATH
from openpilot.iqpilot.selfdrive.iqmodeld.config import ModelConstants
from openpilot.iqpilot.selfdrive.iqmodeld.parser import ArchiveParser
from openpilot.iqpilot.selfdrive.iqmodeld.runtime.ort import ORT_TYPES_TO_NP_TYPES, make_onnx_cpu_runner


def _onnx_dtype_table(session) -> dict[str, np.dtype]:
  return {
    tensor_info.name: ORT_TYPES_TO_NP_TYPES[tensor_info.type]
    for tensor_info in session.get_inputs()
  }


class ONNXRunner(ModelRunner):
  def __init__(self):
    super().__init__()
    self.runner = make_onnx_cpu_runner(MODEL_PATH)
    self._constants = ModelConstants
    self._model_data = self.models.get(ModelType.supercombo)
    self._input_dtypes = _onnx_dtype_table(self.runner)
    self._parser = ArchiveParser()
    self.parser_method_dict[ModelType.supercombo] = self._parser.parse_outputs

  @property
  def input_shapes(self) -> ShapeDict:
    return {tensor_info.name: tensor_info.shape for tensor_info in self.runner.get_inputs()}

  def _frame_as_numpy(self, stream_name: str, imgs_cl: CLMemDict, frames: FrameDict) -> np.ndarray:
    flattened = frames[stream_name].as_numpy(imgs_cl[stream_name])
    shaped = flattened.reshape(self.input_shapes[stream_name])
    return shaped.astype(self._input_dtypes[stream_name])

  def prepare_inputs(self, imgs_cl: CLMemDict, numpy_inputs: NumpyDict, frames: FrameDict) -> dict:
    staged_inputs = dict(numpy_inputs)
    for stream_name in imgs_cl:
      staged_inputs[stream_name] = self._frame_as_numpy(stream_name, imgs_cl, frames)
    self.inputs = staged_inputs
    return staged_inputs

  def _parse_outputs(self, model_outputs: np.ndarray) -> NumpyDict:
    if self._model_data is None:
      raise ValueError("Model data is not available. Ensure the model is loaded correctly.")
    return self.parser_method_dict[self._model_data.model.type.raw](self._slice_outputs(model_outputs))

  def _run_model(self) -> NumpyDict:
    combined = self.runner.run(None, self.inputs)[0].reshape(-1)
    return self._parse_outputs(combined)
