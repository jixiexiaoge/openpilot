from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from openpilot.iqpilot.selfdrive.iqmodeld.models.split_model_constants import SplitModelConstants
from openpilot.iqpilot.selfdrive.iqmodeld.config import ModelConstants


def _bounded_exp(values, out=None):
  return np.exp(np.clip(values, -np.inf, 11), out=out)


def _sigmoid(values):
  return 1.0 / (1.0 + _bounded_exp(-values))


def _softmax_last(values, axis=-1):
  values -= np.max(values, axis=axis, keepdims=True)
  if values.dtype in (np.float32, np.float64):
    _bounded_exp(values, out=values)
  else:
    values = _bounded_exp(values)
  values /= np.sum(values, axis=axis, keepdims=True)
  return values


@dataclass(frozen=True)
class _MixtureRecipe:
  input_heads: int
  output_heads: int
  final_shape: tuple[int, ...]


class _TensorKitchen:
  def __init__(self, ignore_missing: bool = False):
    self.ignore_missing = ignore_missing

  def _grab(self, outputs: dict[str, np.ndarray], tensor_name: str) -> np.ndarray | None:
    if tensor_name not in outputs:
      if not self.ignore_missing:
        raise ValueError(f"Missing output {tensor_name}")
      return
    return outputs[tensor_name]

  def categorical(self, outputs: dict[str, np.ndarray], tensor_name: str, shape=None) -> None:
    raw = self._grab(outputs, tensor_name)
    if raw is None:
      return
    if shape is not None:
      raw = raw.reshape((raw.shape[0],) + shape)
    outputs[tensor_name] = _softmax_last(raw, axis=-1)

  def binary(self, outputs: dict[str, np.ndarray], tensor_name: str) -> None:
    raw = self._grab(outputs, tensor_name)
    if raw is None:
      return
    outputs[tensor_name] = _sigmoid(raw)

  def mixture(self, outputs: dict[str, np.ndarray], tensor_name: str, recipe: _MixtureRecipe) -> None:
    raw = self._grab(outputs, tensor_name)
    if raw is None:
      return

    reshaped = raw.reshape((raw.shape[0], max(recipe.input_heads, 1), -1))
    value_count = (reshaped.shape[2] - recipe.output_heads) // 2
    means = reshaped[:, :, :value_count]
    stds = _bounded_exp(reshaped[:, :, value_count:2 * value_count])

    if recipe.input_heads > 1:
      weights = np.zeros((reshaped.shape[0], recipe.input_heads, recipe.output_heads), dtype=reshaped.dtype)
      for output_idx in range(recipe.output_heads):
        weights[:, :, output_idx - recipe.output_heads] = _softmax_last(
          reshaped[:, :, output_idx - recipe.output_heads], axis=-1
        )

      if recipe.output_heads == 1:
        for batch_idx in range(weights.shape[0]):
          order = np.argsort(weights[batch_idx][:, 0])[::-1]
          weights[batch_idx] = weights[batch_idx][order]
          means[batch_idx] = means[batch_idx][order]
          stds[batch_idx] = stds[batch_idx][order]

      hypothesis_shape = (reshaped.shape[0], recipe.input_heads, *recipe.final_shape)
      outputs[f"{tensor_name}_weights"] = weights
      outputs[f"{tensor_name}_hypotheses"] = means.reshape(hypothesis_shape)
      outputs[f"{tensor_name}_stds_hypotheses"] = stds.reshape(hypothesis_shape)

      picked_means = np.zeros((reshaped.shape[0], recipe.output_heads, value_count), dtype=reshaped.dtype)
      picked_stds = np.zeros((reshaped.shape[0], recipe.output_heads, value_count), dtype=reshaped.dtype)
      for batch_idx in range(weights.shape[0]):
        for output_idx in range(recipe.output_heads):
          order = np.argsort(weights[batch_idx, :, output_idx])[::-1]
          picked_means[batch_idx, output_idx] = means[batch_idx, order[0]]
          picked_stds[batch_idx, output_idx] = stds[batch_idx, order[0]]
    else:
      picked_means = means
      picked_stds = stds

    final_shape = ((reshaped.shape[0], recipe.output_heads, *recipe.final_shape)
                   if recipe.output_heads > 1 else (reshaped.shape[0], *recipe.final_shape))
    outputs[tensor_name] = picked_means.reshape(final_shape)
    outputs[f"{tensor_name}_stds"] = picked_stds.reshape(final_shape)


class ArchiveParser(_TensorKitchen):
  def __init__(self, ignore_missing: bool = False):
    super().__init__(ignore_missing=ignore_missing)
    self._c = ModelConstants

  def _recipes(self) -> list[tuple[str, _MixtureRecipe]]:
    c = self._c
    return [
      ("plan", _MixtureRecipe(c.PLAN_MHP_N, c.PLAN_MHP_SELECTION, (c.IDX_N, c.PLAN_WIDTH))),
      ("lane_lines", _MixtureRecipe(0, 0, (c.NUM_LANE_LINES, c.IDX_N, c.LANE_LINES_WIDTH))),
      ("road_edges", _MixtureRecipe(0, 0, (c.NUM_ROAD_EDGES, c.IDX_N, c.LANE_LINES_WIDTH))),
      ("pose", _MixtureRecipe(0, 0, (c.POSE_WIDTH,))),
      ("road_transform", _MixtureRecipe(0, 0, (c.POSE_WIDTH,))),
      ("wide_from_device_euler", _MixtureRecipe(0, 0, (c.WIDE_FROM_DEVICE_WIDTH,))),
      ("lead", _MixtureRecipe(c.LEAD_MHP_N, c.LEAD_MHP_SELECTION, (c.LEAD_TRAJ_LEN, c.LEAD_WIDTH))),
    ]

  def parse_outputs(self, outputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    c = self._c
    for tensor_name, recipe in self._recipes():
      self.mixture(outputs, tensor_name, recipe)
    if "sim_pose" in outputs:
      self.mixture(outputs, "sim_pose", _MixtureRecipe(0, 0, (c.POSE_WIDTH,)))
    if "lat_planner_solution" in outputs:
      self.mixture(outputs, "lat_planner_solution", _MixtureRecipe(0, 0, (c.IDX_N, c.LAT_PLANNER_SOLUTION_WIDTH)))
    if "desired_curvature" in outputs:
      self.mixture(outputs, "desired_curvature", _MixtureRecipe(0, 0, (c.DESIRED_CURV_WIDTH,)))
    for name in ("lead_prob", "lane_lines_prob", "meta"):
      self.binary(outputs, name)
    self.categorical(outputs, "desire_state", shape=(c.DESIRE_PRED_WIDTH,))
    self.categorical(outputs, "desire_pred", shape=(c.DESIRE_PRED_LEN, c.DESIRE_PRED_WIDTH))
    return outputs


class PhaseParser(_TensorKitchen):
  def __init__(self, ignore_missing: bool = False):
    super().__init__(ignore_missing=ignore_missing)
    self._c = SplitModelConstants

  def _has_mixture_heads(self, outputs: dict[str, np.ndarray], tensor_name: str, flat_width: int) -> bool:
    raw = self._grab(outputs, tensor_name)
    if raw is None:
      return False
    return raw.shape[1] != 2 * flat_width

  def _decode_dynamic_family(self, outputs: dict[str, np.ndarray]) -> None:
    c = self._c
    if "lead" in outputs:
      uses_heads = self._has_mixture_heads(outputs, "lead", c.LEAD_MHP_SELECTION * c.LEAD_TRAJ_LEN * c.LEAD_WIDTH)
      self.mixture(outputs, "lead", _MixtureRecipe(
        c.LEAD_MHP_N if uses_heads else 0,
        c.LEAD_MHP_SELECTION if uses_heads else 0,
        (c.LEAD_TRAJ_LEN, c.LEAD_WIDTH) if uses_heads else (c.LEAD_MHP_SELECTION, c.LEAD_TRAJ_LEN, c.LEAD_WIDTH),
      ))

    if "plan" in outputs:
      uses_heads = self._has_mixture_heads(outputs, "plan", c.IDX_N * c.PLAN_WIDTH)
      self.mixture(outputs, "plan", _MixtureRecipe(
        c.PLAN_MHP_N if uses_heads else 0,
        c.PLAN_MHP_SELECTION if uses_heads else 0,
        (c.IDX_N, c.PLAN_WIDTH),
      ))

    if "planplus" in outputs:
      self.mixture(outputs, "planplus", _MixtureRecipe(0, 0, (c.IDX_N, c.PLAN_WIDTH)))

  def _decode_policy_family(self, outputs: dict[str, np.ndarray]) -> None:
    c = self._c
    if "action" in outputs:
      self.mixture(outputs, "action", _MixtureRecipe(0, 0, (c.ACTION_WIDTH,)))
    if "desired_curvature" in outputs:
      self.mixture(outputs, "desired_curvature", _MixtureRecipe(0, 0, (c.DESIRED_CURV_WIDTH,)))
    if "desire_pred" in outputs:
      self.categorical(outputs, "desire_pred", shape=(c.DESIRE_PRED_LEN, c.DESIRE_PRED_WIDTH))
    if "desire_state" in outputs:
      self.categorical(outputs, "desire_state", shape=(c.DESIRE_PRED_WIDTH,))
    if "lane_lines" in outputs:
      self.mixture(outputs, "lane_lines", _MixtureRecipe(0, 0, (c.NUM_LANE_LINES, c.IDX_N, c.LANE_LINES_WIDTH)))
    if "lane_lines_prob" in outputs:
      self.binary(outputs, "lane_lines_prob")
    if "lead_prob" in outputs:
      self.binary(outputs, "lead_prob")
    if "lat_planner_solution" in outputs:
      self.mixture(outputs, "lat_planner_solution", _MixtureRecipe(0, 0, (c.IDX_N, c.LAT_PLANNER_SOLUTION_WIDTH)))
    if "meta" in outputs:
      self.binary(outputs, "meta")
    if "road_edges" in outputs:
      self.mixture(outputs, "road_edges", _MixtureRecipe(0, 0, (c.NUM_ROAD_EDGES, c.IDX_N, c.LANE_LINES_WIDTH)))
    if "sim_pose" in outputs:
      self.mixture(outputs, "sim_pose", _MixtureRecipe(0, 0, (c.POSE_WIDTH,)))

  def parse_vision_outputs(self, outputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    c = self._c
    self.mixture(outputs, "pose", _MixtureRecipe(0, 0, (c.POSE_WIDTH,)))
    self.mixture(outputs, "wide_from_device_euler", _MixtureRecipe(0, 0, (c.WIDE_FROM_DEVICE_WIDTH,)))
    self.mixture(outputs, "road_transform", _MixtureRecipe(0, 0, (c.POSE_WIDTH,)))
    self._decode_dynamic_family(outputs)
    self._decode_policy_family(outputs)
    return outputs

  def parse_policy_outputs(self, outputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    self._decode_dynamic_family(outputs)
    self._decode_policy_family(outputs)
    return outputs

  def parse_outputs(self, outputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return self.parse_policy_outputs(self.parse_vision_outputs(outputs))


__all__ = [
  "ArchiveParser",
  "PhaseParser",
]
