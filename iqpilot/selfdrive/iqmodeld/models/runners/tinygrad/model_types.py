"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Callable

import numpy as np

from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import ModelType, NumpyDict
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import RunnerRoot
from openpilot.iqpilot.selfdrive.iqmodeld.parser import ArchiveParser, PhaseParser


class _ParserRole(RunnerRoot, ABC):
  def _bind_parser_role(self,
                        selector: int,
                        parser_builder: Callable[[], object],
                        projector: Callable[[object, NumpyDict], NumpyDict]) -> None:
    parser = parser_builder()
    self.parser_method_dict[selector] = lambda model_blob: projector(parser, self._slice_outputs(model_blob))


def _phase_policy(parser: PhaseParser, sliced_outputs: NumpyDict) -> NumpyDict:
  return parser.parse_policy_outputs(sliced_outputs)


def _phase_vision(parser: PhaseParser, sliced_outputs: NumpyDict) -> NumpyDict:
  return parser.parse_vision_outputs(sliced_outputs)


def _archive_combined(parser: ArchiveParser, sliced_outputs: NumpyDict) -> NumpyDict:
  return parser.parse_outputs(sliced_outputs)


class OffPolicyTinygrad(_ParserRole, ABC):
  def __init__(self):
    self._bind_parser_role(ModelType.offPolicy, PhaseParser, _phase_policy)


class OnPolicyTinygrad(_ParserRole, ABC):
  def __init__(self):
    self._bind_parser_role(ModelType.onPolicy, PhaseParser, _phase_policy)


class PolicyTinygrad(_ParserRole, ABC):
  def __init__(self):
    self._bind_parser_role(ModelType.policy, PhaseParser, _phase_policy)


class VisionTinygrad(_ParserRole, ABC):
  def __init__(self):
    self._bind_parser_role(ModelType.vision, PhaseParser, _phase_vision)


class SupercomboTinygrad(_ParserRole, ABC):
  def __init__(self):
    self._bind_parser_role(ModelType.supercombo, ArchiveParser, _archive_combined)
