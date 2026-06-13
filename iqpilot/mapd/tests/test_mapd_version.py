"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.iqpilot import get_file_hash
from openpilot.iqpilot.mapd import MAPD_PATH
from openpilot.iqpilot.mapd.update_version import MAPD_HASH_PATH


class TestMapdVersion:
  def test_compare_versions(self):
    mapd_hash = get_file_hash(MAPD_PATH)

    with open(MAPD_HASH_PATH) as f:
      current_hash = f.read().strip()

    assert current_hash == mapd_hash, "Run iqpilot/mapd/update_version.py to update the current mapd version and hash"
