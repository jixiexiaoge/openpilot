"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.iqpilot.iq_maps.vendor_mapd_installer import get_file_hash
from openpilot.iqpilot.iq_maps import VENDOR_MAPD_PATH
from openpilot.iqpilot.iq_maps.update_vendor_version import MAPD_HASH_PATH


class TestMapdVersion:
  def test_compare_versions(self):
    mapd_hash = get_file_hash(VENDOR_MAPD_PATH)

    with open(MAPD_HASH_PATH) as f:
      current_hash = f.read().strip()

    assert current_hash == mapd_hash, "Run iqpilot/iq_maps/update_vendor_version.py to update the current mapd version and hash"
