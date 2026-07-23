"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
import itertools

import numpy as np
import onnx
import onnxruntime as ort


ORT_TYPES_TO_NP_TYPES = {
  "tensor(float16)": np.float16,
  "tensor(float)": np.float32,
  "tensor(uint8)": np.uint8,
}


def _promote_raw_half_blob(attribute):
  float32_values = np.frombuffer(attribute.raw_data, dtype=np.float16)
  attribute.data_type = 1
  attribute.raw_data = float32_values.astype(np.float32).tobytes()


def _rewrite_tensor_io_types(model):
  for value_info in itertools.chain(model.graph.input, model.graph.output):
    if value_info.type.tensor_type.elem_type == 10:
      value_info.type.tensor_type.elem_type = 1


def _rewrite_cast_nodes(model):
  for node in model.graph.node:
    if node.op_type == "Cast" and node.attribute[0].i == 10:
      node.attribute[0].i = 1
    for attribute in node.attribute:
      if hasattr(attribute, "t") and attribute.t.data_type == 10:
        _promote_raw_half_blob(attribute.t)


def attributeproto_fp16_to_fp32(attr):
  _promote_raw_half_blob(attr)


def convert_fp16_to_fp32(model):
  for initializer in model.graph.initializer:
    if initializer.data_type == 10:
      _promote_raw_half_blob(initializer)
  _rewrite_tensor_io_types(model)
  _rewrite_cast_nodes(model)
  return model.SerializeToString()


def _cpu_session_options():
  options = ort.SessionOptions()
  options.intra_op_num_threads = 4
  options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
  options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
  return options


def make_onnx_cpu_runner(model_path):
  model_blob = convert_fp16_to_fp32(onnx.load(model_path))
  return ort.InferenceSession(model_blob, _cpu_session_options(), providers=["CPUExecutionProvider"])
