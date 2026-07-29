"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import os
import pickle as _pk
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from cereal import custom
from openpilot.system.hardware import TICI
from openpilot.system.hardware.hw import Paths as _hw_paths
from openpilot.iqpilot.selfdrive.iqmodeld.models.helpers import get_active_bundle as _fetch_bundle
from openpilot.iqpilot.selfdrive.iqmodeld.models.combined_artifact import has_combined_split_artifact

# ---- runtime type surface (native OpenCL/frame handles resolve to Any off-device) ----
if TYPE_CHECKING:
  from openpilot.iqpilot.selfdrive.iqmodeld.native.iqmodel_pyx import GpuMemorySlot, RoadProjector
else:
  def _resolve_native_types() -> tuple[Any, Any]:
    try:
      from openpilot.iqpilot.selfdrive.iqmodeld.native.iqmodel_pyx import GpuMemorySlot as iq_clmem
      from openpilot.iqpilot.selfdrive.iqmodeld.native.iqmodel_pyx import RoadProjector as iq_frame
      return iq_clmem, iq_frame
    except (ModuleNotFoundError, ImportError):
      return Any, Any

  GpuMemorySlot, RoadProjector = _resolve_native_types()

NumpyDict = dict[str, np.ndarray]
ShapeDict = dict[str, tuple[int, ...]]
SliceDict = dict[str, slice]
CLMemDict = dict[str, GpuMemorySlot]
FrameDict = dict[str, RoadProjector]

ModelType = custom.IQModelManager.Model.Type
Model = custom.IQModelManager.Model

SEND_RAW_PRED = os.getenv("SEND_RAW_PRED")
CUSTOM_MODEL_PATH = _hw_paths.model_root()

_META_FIELDS = ("input_shapes", "output_slices")

USBGPU = "USBGPU" in os.environ


def _configure_accelerator():
  """Point tinygrad at the right backend. Must run before tinygrad is imported,
  which is why it fires at module import."""
  backend, extra = ("QCOM" if TICI else "CPU"), {}
  if USBGPU:
    backend, extra = "AMD", {"AMD_IFACE": "USB"}
  elif TICI:
    extra = {"QCOM_PRIORITY": "8"}
  os.environ["DEV"] = backend
  os.environ.update(extra)


_configure_accelerator()


def load_artifact_metadata(metadata_filename):
  """Read one artifact's metadata pkl: (input shapes, output slices)."""
  with open(os.path.join(CUSTOM_MODEL_PATH, metadata_filename), 'rb') as fh:
    blob = _pk.load(fh)
  return tuple(blob.get(field, {}) for field in _META_FIELDS)


@dataclass
class ArtifactSpec:
  """One model of the active bundle plus its unpacked metadata."""
  model: Any
  metadata: Any = None
  input_shapes: ShapeDict = field(default_factory=dict)
  output_slices: SliceDict = field(default_factory=dict)

  def __post_init__(self):
    self.metadata = self.model.metadata
    if self.metadata:
      self.input_shapes, self.output_slices = load_artifact_metadata(self.metadata.fileName)


# kept name: some runners annotate against the old alias
ModelData = ArtifactSpec


class RunnerRoot:
  """Shared root of the runner hierarchy.

  Both ModelRunner and the per-model parser mixins (model_types.py) inherit
  this, so the concrete `TinygradRunner(ModelRunner, *Tinygrad)` diamond keeps
  one consistent parser registry + slice implementation.
  """

  parser_method_dict: dict
  _model_data: "ArtifactSpec | None"

  def _slice_outputs(self, model_outputs):
    raise NotImplementedError


class ModelRunner(RunnerRoot):
  """Base for the tinygrad/ONNX runners.

  Owns the active bundle's ArtifactSpecs and the shared slice/parse plumbing;
  subclasses provide input staging (prepare_inputs) and execution (_run_model).
  """

  # False for fused runners, which warp + manage temporal buffers inside the JIT
  uses_opencl_warp = True

  def __init__(self):
    active = _fetch_bundle()
    if not active:
      raise ValueError("runner started without an active model bundle")

    self.models = {spec.type.raw: ArtifactSpec(spec) for spec in active.models}
    self.is_20hz_3d = False
    self.is_20hz = active.is20hz
    self.inputs = {}
    self.parser_method_dict = {}
    self._model_data = None            # active spec for the current operation
    self._parser = self._constants = None

  def _active_spec(self):
    spec = self._model_data
    if spec is None:
      raise ValueError("Model data is not available. Ensure the model is loaded correctly.")
    return spec

  # views proxied straight off the active artifact spec; kept out of the class
  # body (served via __getattr__) so the read surface stays data-driven
  _SPEC_VIEW = frozenset(("input_shapes", "output_slices"))

  def __getattr__(self, name):
    if name == "constants":
      return self._constants
    if name == "vision_input_names":
      return list(self._active_spec().input_shapes)
    if name in ModelRunner._SPEC_VIEW:
      return getattr(self._active_spec(), name)
    raise AttributeError(name)

  def prepare_inputs(self, imgs_cl, numpy_inputs, frames):
    """Stage image + numpy inputs for inference; implemented per backend."""
    raise NotImplementedError

  def _run_model(self):
    """Execute inference over the staged inputs; implemented per backend."""
    raise NotImplementedError

  def run_model(self):
    # parsing happens inside each backend's _run_model
    return self._run_model()

  def _slice_outputs(self, model_outputs):
    """Split the flat output vector into named views per the artifact's slice table."""
    sliced = {}
    for tag, span in self._active_spec().output_slices.items():
      sliced[tag] = model_outputs[np.newaxis, span]
    if SEND_RAW_PRED:
      sliced["raw_pred"] = model_outputs.copy()
    return sliced


# ---- runner selection (which backend to build for the active bundle) ----------

def _single_artifact_prefix(bundle, prefix: str) -> bool:
  return len(bundle.models) == 1 and bundle.models[0].artifact.fileName.startswith(prefix)


def _is_fused_bundle(bundle) -> bool:
  return _single_artifact_prefix(bundle, "driving_fused_")


def _is_supercombo_bundle(bundle) -> bool:
  return _single_artifact_prefix(bundle, "driving_supercombo_")


def _is_split_bundle(bundle) -> bool:
  present = {m.type.raw for m in bundle.models}
  split_kinds = {ModelType.vision, ModelType.policy, ModelType.offPolicy, ModelType.onPolicy}
  return not present.isdisjoint(split_kinds)


def get_model_runner() -> "ModelRunner":
  """Build the runner backend that fits the active bundle (supercombo / fused /
  combined-split / split / single). Concrete runners are imported lazily so one
  backend failing to load can't take down the others at import time."""
  from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.tinygrad.tinygrad_runner import (TinygradRunner,
                                                                                             TinygradSplitRunner)
  bundle = _fetch_bundle()
  if not (bundle and bundle.models):
    return TinygradRunner(ModelType.supercombo)

  if _is_supercombo_bundle(bundle):
    from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.tinygrad.supercombo_runner import TinygradSupercomboRunner
    return TinygradSupercomboRunner()
  if _is_fused_bundle(bundle):
    from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.tinygrad.fused_runner import TinygradFusedRunner
    return TinygradFusedRunner()
  if _is_split_bundle(bundle) and has_combined_split_artifact(bundle):
    from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.tinygrad.combined_split_runner import TinygradCombinedSplitRunner
    return TinygradCombinedSplitRunner()
  if _is_split_bundle(bundle):
    return TinygradSplitRunner()
  return TinygradRunner(bundle.models[0].type.raw)
