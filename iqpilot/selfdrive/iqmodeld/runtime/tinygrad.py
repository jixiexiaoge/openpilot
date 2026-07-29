"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
from tinygrad.tensor import Tensor
from tinygrad.helpers import to_mv

_PTR_STRIDE = 8
_RAW_GPU_PTR_SLOT = 20
_RAW_GPU_PTR_VIEW_BYTES = 0x100


def _descriptor_pointer(opencl_address: int) -> int:
  return to_mv(opencl_address, _PTR_STRIDE).cast("Q")[0]


def _raw_gpu_pointer(descriptor_pointer: int) -> int:
  return to_mv(descriptor_pointer, _RAW_GPU_PTR_VIEW_BYTES).cast("Q")[_RAW_GPU_PTR_SLOT]


def qcom_tensor_from_opencl_address(opencl_address, shape, dtype):
  descriptor_pointer = _descriptor_pointer(opencl_address)
  device_pointer = _raw_gpu_pointer(descriptor_pointer)
  return Tensor.from_blob(device_pointer, shape, dtype=dtype, device="QCOM")
