import json
import os

from iqdbc.car.common.basedir import BASEDIR
from iqdbc.iqpilot.car.platform_list import get_car_list

CATALOG_JSON = os.path.join(BASEDIR, "..", "..", "iqpilot", "selfdrive", "car", "vehicle_catalog.json")

_KEY_TO_ATTR = {"id": "platform", "mk": "make", "grp": "brand", "mdl": "model", "yrs": "year", "req": "package"}


def _decode(envelope) -> dict:
  out = {}
  for record in (envelope.get("vehicles") or {}).values():
    out[record.get("label", "")] = {attr: record.get(key) for key, attr in _KEY_TO_ATTR.items()}
  return out


class TestCarList:
  def test_generator(self):
    generated = get_car_list()
    with open(CATALOG_JSON) as f:
      shipped = _decode(json.load(f))

    assert shipped == generated, "Run: python -m openpilot.iqpilot.selfdrive.car.vehicle_catalog"
