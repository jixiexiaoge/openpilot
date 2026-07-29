from __future__ import annotations

from collections.abc import Iterable


FALLBACK_MOTDS = ("Drive safely. Stay focused.",)
_BUNDLE_NAME = "iqpilot_hephaestusd_private"
_MODULE_NAME = "iqpilot_private.konn3kt.hephaestus.motd"


def _dongle_id() -> str | None:
  try:
    from openpilot.common.params import Params
    return Params().get("DongleId", encoding="utf-8")
  except Exception:
    return None


def _clean_messages(messages: object) -> list[str]:
  if not isinstance(messages, Iterable) or isinstance(messages, (str, bytes)):
    return []
  return [message.strip() for message in messages if isinstance(message, str) and message.strip()]


def load_motds(dongle_id: str | None = None) -> list[str]:
  try:
    from openpilot.system.proprietary_runtime._verified_import import import_verified_module
    module = import_verified_module(_BUNDLE_NAME, _MODULE_NAME)
    messages = module.messages_for_dongle(_dongle_id() if dongle_id is None else dongle_id)
    cleaned = _clean_messages(messages)
    if cleaned:
      return cleaned
  except Exception:
    pass
  return list(FALLBACK_MOTDS)
