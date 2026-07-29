"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.iqpilot.iq_maps.vendor_mapd_installer import sha256_of_file
from openpilot.iqpilot.iq_maps import VENDOR_MAPD_PATH
from openpilot.iqpilot.iq_maps.update_vendor_version import HASH_FILE


class TestMapdVersion:
  def test_compare_versions(self):
    mapd_hash = sha256_of_file(VENDOR_MAPD_PATH)

    with open(HASH_FILE) as f:
      current_hash = f.read().strip()

    assert current_hash == mapd_hash, "Run iqpilot/iq_maps/update_vendor_version.py to update the current mapd version and hash"
