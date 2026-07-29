#!/usr/bin/env python3
"""Real-CAN replay invariant tests for VW torque platforms (PQ / MQB / MLB).

Replays real konn3kt routes through the car interface with openpilot lateral
INACTIVE (latActive=False) and asserts openpilot never transmits an active-steering
HCA command (active status or non-zero torque). Re-transmitting the stock camera's
active HCA while not in control (stock-LKAS forwarding) leaves the EPS faulted for
the whole drive (LH2_Sta_HCA=FAULT) - the regression that bricked steering on a PQ
Passat NMS with a factory LKAS camera. Panda accepts these frames, so only a replay
invariant like this catches it.

Self-contained within iqdbc: routes are resolved through konn3kt's public
/v1/route/<id>/files endpoint (URLs are signed server-side, no auth/token needed).
"""
import json
import os
import urllib.parse
import urllib.request
from collections import Counter

import pytest

from iqdbc.can.parser import CANParser
from iqdbc.car import Bus, structs
from iqdbc.car.can_definitions import CanData
from iqdbc.car.car_helpers import can_fingerprint, interfaces
from iqdbc.car.logreader import LogReader
from iqdbc.car.volkswagen.values import CAR, DBC, VolkswagenFlags

API_HOST = os.environ.get("API_HOST", "https://api-iqlabs.konn3kt.com")

# konn3kt-hosted VW routes. (route_id, segment, platform, label)
# Add MQB routes here as konn3kt-hosted MQB logs become available.
VW_ROUTES = [
  ("b29ee8c5a0a735d1|000000dc--a384e9083e", 0, CAR.VOLKSWAGEN_PASSAT_NMS, "PQ with stock LKAS camera"),
  ("0f53129ed44f6920|00000287--3efbddeb96", 0, CAR.VOLKSWAGEN_PASSAT_NMS, "PQ without stock LKAS camera"),
]

# Per-platform HCA message: (address, msg, status signal, torque signal, active-status values)
HCA_INFO = {
  "pq": (0xD2, "HCA_1", "HCA_Status", "LM_Offset", (5, 7)),
  "mqb": (0x126, "HCA_01", "HCA_01_Status_HCA", "HCA_01_LM_Offset", (5, 6, 7)),
}


def _request_headers() -> dict[str, str]:
  # konn3kt's edge rejects the default urllib User-Agent with 403. The routes are public
  # (access returns early for public routes), but IQ.Pilot/Cabana tooling conventionally
  # sends a Konn3kt user JWT, so include one when available (env or ~/.comma/auth.json).
  headers = {"User-Agent": "iqdbc"}
  token = os.environ.get("KONN3KT_ACCESS_TOKEN")
  if not token:
    try:
      with open(os.path.expanduser("~/.comma/auth.json")) as f:
        token = json.load(f).get("access_token")
    except (OSError, ValueError):
      token = None
  if token:
    headers["Authorization"] = f"JWT {token}"
  return headers


def _rlog_url(route_id: str, segment: int) -> str:
  req = urllib.request.Request(f"{API_HOST}/v1/route/{urllib.parse.quote(route_id, safe='|')}/files",
                               headers=_request_headers())
  with urllib.request.urlopen(req, timeout=30) as f:
    files = json.load(f)
  for url in files.get("logs", []):
    # path looks like /connectdata/<dongle>/<log>/<seg>/rlog.zst
    parts = urllib.parse.urlparse(url).path.rstrip("/").split("/")
    if len(parts) >= 2 and parts[-2] == str(segment):
      return url
  raise RuntimeError(f"no rlog for {route_id} segment {segment} (uploaded & public?)")


def _load_can(route_id: str, segment: int):
  lr = LogReader(_rlog_url(route_id, segment), only_union_types=True, sort_by_time=True)
  return [(m.logMonoTime, [CanData(c.address, c.dat, c.src) for c in m.can]) for m in lr if m.which() == "can"]


@pytest.mark.parametrize("route_id,segment,platform,label", VW_ROUTES)
def test_vw_inactive_steering_invariant(route_id, segment, platform, label):
  can_msgs = _load_can(route_id, segment)
  assert len(can_msgs) > 1000, f"insufficient CAN data for {label}: {len(can_msgs)} frames"

  # fingerprint from a fresh iterator over the (unmutated) frame list
  frame_iter = (frames for _, frames in can_msgs)
  def can_recv(wait_for_one: bool = False):
    return [next(frame_iter, [])]
  _, fingerprint = can_fingerprint(can_recv)

  CarInterface = interfaces[platform]
  CP = CarInterface.get_params(platform, fingerprint, [], False, False, False)
  CP_IQ = CarInterface.get_params_iq(CP, platform, fingerprint, [], False, False, False)

  if CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
    pytest.skip("invariant covers torque-based VW platforms (PQ/MQB/MLB)")

  key = "pq" if CP.flags & VolkswagenFlags.PQ else "mqb"
  hca_addr, hca_msg, status_sig, torque_sig, active_status = HCA_INFO[key]
  cp = CANParser(DBC[platform][Bus.pt], [(hca_msg, 0)], 0)

  CI = CarInterface(CP, CP_IQ)
  CC = structs.CarControl().as_reader()  # latActive defaults to False
  CC_IQ = structs.IQCarControl()

  hca_seen = 0
  violations = Counter()
  for i, (mono, frames) in enumerate(can_msgs):
    CI.update([(mono, frames)])
    _, sendcan = CI.apply(CC, CC_IQ, mono)

    if i < 300:  # CarController / CANParser warmup
      continue

    for addr, dat, bus in sendcan:
      if addr != hca_addr or bus != 0:
        continue
      hca_seen += 1
      cp.update([(mono, [(addr, bytes(dat), 0)])])
      if int(cp.vl[hca_msg][status_sig]) in active_status:
        violations["active_status"] += 1
      if abs(cp.vl[hca_msg][torque_sig]) > 0:
        violations["nonzero_torque"] += 1

  assert hca_seen > 50, f"{label}: no HCA steering messages transmitted to inspect"
  assert not len(violations), \
    f"{label}: openpilot TX'd active HCA while latActive=False: {dict(violations)}"


if __name__ == "__main__":
  import sys
  sys.exit(pytest.main([__file__, "-v"]))
