from types import SimpleNamespace

import pytest

from openpilot.selfdrive.monitoring.dmonitoringd import get_dm_inputs


@pytest.mark.parametrize("enabled, lat_active, expected", [
  (False, False, False),
  (True, False, True),
  (False, True, True),
  (True, True, True),
])
def test_iq_enabled_adapter(enabled, lat_active, expected):
  sm = {
    'driverStateV2': object(),
    'liveCalibration': object(),
    'carState': object(),
    'selfdriveState': SimpleNamespace(enabled=enabled),
    'modelV2': object(),
    'carControl': SimpleNamespace(latActive=lat_active),
  }

  assert get_dm_inputs(sm)['selfdriveState'].enabled == expected
