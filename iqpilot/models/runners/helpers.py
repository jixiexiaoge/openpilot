from openpilot.iqpilot.models.helpers import get_active_bundle
from openpilot.iqpilot.models.runners.model_runner import ModelRunner
from openpilot.iqpilot.models.runners.tinygrad.tinygrad_runner import TinygradRunner, TinygradSplitRunner
from openpilot.iqpilot.models.runners.constants import ModelType


def _is_fused_bundle(bundle) -> bool:
  return len(bundle.models) == 1 and bundle.models[0].artifact.fileName.startswith("driving_fused_")


def _is_supercombo_bundle(bundle) -> bool:
  return len(bundle.models) == 1 and bundle.models[0].artifact.fileName.startswith("driving_supercombo_")


def get_model_runner() -> ModelRunner:
  """
  Factory function to create and return the appropriate ModelRunner instance.

  Selects TinygradRunner, choosing TinygradSplitRunner if separate vision/policy
  models are detected in the active bundle.

  :return: An instance of a ModelRunner subclass (ONNXRunner, TinygradRunner, or TinygradSplitRunner).
  """
  bundle = get_active_bundle()
  if bundle and bundle.models:
    if _is_supercombo_bundle(bundle):
      # lazy import so a runner issue can't break other bundles at import
      from openpilot.iqpilot.models.runners.tinygrad.supercombo_runner import TinygradSupercomboRunner
      return TinygradSupercomboRunner()

    if _is_fused_bundle(bundle):
      # lazy import so a fused-runner issue can't break non-fused bundles at import
      from openpilot.iqpilot.models.runners.tinygrad.fused_runner import TinygradFusedRunner
      return TinygradFusedRunner()

    model_types = {m.type.raw for m in bundle.models}
    split_types = {ModelType.vision, ModelType.policy, ModelType.offPolicy, ModelType.onPolicy}
    if model_types & split_types:
      return TinygradSplitRunner()
    if bundle.models:
      return TinygradRunner(bundle.models[0].type.raw)

  return TinygradRunner(ModelType.supercombo)
