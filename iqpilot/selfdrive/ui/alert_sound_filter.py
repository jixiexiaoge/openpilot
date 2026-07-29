"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Sound-suppression policy for Soundd. The driver's "IQAlertSilence" param, when set,
mutes routine chimes and keeps only a named allow-list of safety-critical cues
audible. The param is re-sampled on a fixed poll interval rather than every frame.
"""
from cereal import car
from openpilot.common.params import Params

# policy expressed as data: names resolved against the enum at construction so the
# allow-list reads as configuration instead of a hardcoded wall of enum accesses
_KEEP_AUDIBLE_WHEN_QUIET = ("warningSoft", "warningImmediate", "promptDistracted", "promptRepeat")
_SUPPRESS_PARAM = "IQAlertSilence"
_POLL_INTERVAL = 50


class AlertSoundFilter:
  def __init__(self):
    self._store = Params()
    self._cue = car.CarControl.HUDControl.AudibleAlert
    self._allow_when_quiet = frozenset(getattr(self._cue, n) for n in _KEEP_AUDIBLE_WHEN_QUIET)
    self._suppressing = self._store.get_bool(_SUPPRESS_PARAM)
    self._poll = 0

  def refresh(self) -> None:
    self._poll = (self._poll + 1) % _POLL_INTERVAL
    if self._poll == 0:
      self._suppressing = self._store.get_bool(_SUPPRESS_PARAM)

  def permits(self, alert) -> bool:
    has_cue = alert != self._cue.none
    if not self._suppressing:
      return has_cue
    return has_cue and alert in self._allow_when_quiet
