"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import json
import os

from openpilot.common.basedir import BASEDIR

SCHEMA = "iqlvbs/supported-vehicles"
REV = 1

CATALOG_FILENAME = "vehicle_catalog.json"
_CANDIDATE_PARTS = (
  ("iqpilot", "selfdrive", "car", CATALOG_FILENAME),
)

# in-memory (car-interface) field  ->  on-disk compact key
_ATTR_TO_KEY = (
  ("platform", "id"),
  ("make", "mk"),
  ("brand", "grp"),
  ("model", "mdl"),
  ("year", "yrs"),
  ("package", "req"),
)


def _reference(platform: str, years: list[str], claimed: set[str]) -> str:
  span = f"{years[0]}-{years[-1]}" if len(years) > 1 else (years[0] if years else "na")
  stem = f"{platform}|{span}"
  ref, bump = stem, 2
  while ref in claimed:
    ref = f"{stem}#{bump}"
    bump += 1
  claimed.add(ref)
  return ref


def encode(vehicles: dict[str, dict]) -> dict:
  records: dict[str, dict] = {}
  claimed: set[str] = set()
  for label, attrs in vehicles.items():
    years = list(attrs.get("year") or [])
    ref = _reference(attrs.get("platform", ""), years, claimed)
    record = {"label": label}
    for attr, key in _ATTR_TO_KEY:
      record[key] = attrs.get(attr)
    records[ref] = record
  return {"catalog": SCHEMA, "rev": REV, "vehicles": records}


def decode(envelope: dict) -> dict[str, dict]:
  vehicles: dict[str, dict] = {}
  for record in (envelope.get("vehicles") or {}).values():
    attrs = {attr: record.get(key) for attr, key in _ATTR_TO_KEY}
    vehicles[record.get("label", "")] = attrs
  return vehicles


def catalog_path(basedir: str = BASEDIR) -> str | None:
  for parts in _CANDIDATE_PARTS:
    candidate = os.path.join(basedir, *parts)
    if os.path.isfile(candidate):
      return candidate
  return None


def load_catalog(basedir: str = BASEDIR) -> dict[str, dict]:
  path = catalog_path(basedir)
  if path is None:
    return {}
  with open(path) as handle:
    return decode(json.load(handle))


def _write(vehicles: dict[str, dict], basedir: str = BASEDIR) -> str:
  out = os.path.join(basedir, "iqpilot", "selfdrive", "car", CATALOG_FILENAME)
  with open(out, "w") as handle:
    json.dump(encode(vehicles), handle, indent=2, ensure_ascii=False)
  return out


if __name__ == "__main__":
  from iqdbc.iqpilot.car.platform_list import get_car_list
  print("wrote", _write(get_car_list()))
