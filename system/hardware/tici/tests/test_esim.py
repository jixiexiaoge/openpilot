import pytest
from contextlib import contextmanager

from openpilot.system.hardware import HARDWARE, TICI
from openpilot.system.hardware.base import LPAError, LPAProfileNotFoundError, Profile
from openpilot.system.hardware.tici import lpa as lpa_module
from openpilot.system.hardware.tici.esim_manager import EsimManager

# https://euicc-manual.osmocom.org/docs/rsp/known-test-profile
# iccid is always the same for the given activation code
TEST_ACTIVATION_CODE = 'LPA:1$rsp.truphone.com$QRF-BETTERROAMING-PMRDGIR2EARDEIT5'
TEST_ICCID = '8944476500001944011'

TEST_NICKNAME = 'test_profile'

def cleanup():
  lpa = HARDWARE.get_sim_lpa()
  try:
    lpa.delete_profile(TEST_ICCID)
  except LPAProfileNotFoundError:
    pass
  lpa.process_notifications()

class TestEsim:

  @classmethod
  def setup_class(cls):
    if not TICI:
      pytest.skip()
    cleanup()

  @classmethod
  def teardown_class(cls):
    cleanup()

  def test_provision_enable_disable(self):
    lpa = HARDWARE.get_sim_lpa()
    current_active = lpa.get_active_profile()

    lpa.download_profile(TEST_ACTIVATION_CODE, TEST_NICKNAME)
    assert any(p.iccid == TEST_ICCID and p.nickname == TEST_NICKNAME for p in lpa.list_profiles())

    lpa.enable_profile(TEST_ICCID)
    new_active = lpa.get_active_profile()
    assert new_active is not None
    assert new_active.iccid == TEST_ICCID
    assert new_active.nickname == TEST_NICKNAME

    lpa.disable_profile(TEST_ICCID)
    new_active = lpa.get_active_profile()
    assert new_active is None

    if current_active:
      lpa.enable_profile(current_active.iccid)


class TestEsimDeleteHandling:
  def test_delete_ignores_notification_cleanup_if_profile_is_gone(self, monkeypatch):
    target_iccid = "89012804332267989477"
    lpa = lpa_module.TiciLPA()

    monkeypatch.setattr(lpa, "_validate_profile_exists", lambda iccid: None)
    monkeypatch.setattr(lpa, "get_active_profile", lambda: Profile("8901240527117095243", "US Mobile", True, "Wireless"))
    monkeypatch.setattr(lpa, "_restart_modem", lambda: None)
    monkeypatch.setattr(
      lpa,
      "list_profiles",
      lambda: [Profile("8901240527117095243", "US Mobile", True, "Wireless")],
    )

    @contextmanager
    def fake_open_client():
      yield object()

    monkeypatch.setattr(lpa, "_open_client", fake_open_client)
    monkeypatch.setattr(lpa_module, "delete_profile", lambda client, iccid: None)

    def fail_notifications(client):
      raise RuntimeError('AT command failed (AT+CGLA=2,16,"80E2910003BF2800"): AT command failed')

    monkeypatch.setattr(lpa_module, "process_notifications", fail_notifications)

    lpa.delete_profile(target_iccid)

  def test_delete_raises_clear_error_if_profile_still_present_after_cleanup_failure(self, monkeypatch):
    target_iccid = "89012804332267989477"
    lpa = lpa_module.TiciLPA()

    monkeypatch.setattr(lpa, "_validate_profile_exists", lambda iccid: None)
    monkeypatch.setattr(lpa, "get_active_profile", lambda: Profile("8901240527117095243", "US Mobile", True, "Wireless"))
    monkeypatch.setattr(lpa, "_restart_modem", lambda: None)
    monkeypatch.setattr(
      lpa,
      "list_profiles",
      lambda: [
        Profile("8901240527117095243", "US Mobile", True, "Wireless"),
        Profile(target_iccid, "RedPocket", False, "RedPocket"),
      ],
    )

    @contextmanager
    def fake_open_client():
      yield object()

    monkeypatch.setattr(lpa, "_open_client", fake_open_client)
    monkeypatch.setattr(lpa_module, "delete_profile", lambda client, iccid: None)

    def fail_notifications(client):
      raise RuntimeError('AT command failed (AT+CGLA=2,16,"80E2910003BF2800"): AT command failed')

    monkeypatch.setattr(lpa_module, "process_notifications", fail_notifications)

    with pytest.raises(LPAError, match="Profile delete did not finish cleanly"):
      lpa.delete_profile(target_iccid)

  def test_manager_maps_notification_cleanup_error(self):
    error = LPAError('AT command failed (AT+CGLA=2,16,"80E2910003BF2800"): AT command failed')
    assert EsimManager._map_error(error) == "Modem notification cleanup failed; refresh profiles"


class TestEsimNotificationCleanupRecovery:
  def test_switch_ignores_notification_cleanup_if_target_is_enabled(self, monkeypatch):
    target_iccid = "8901240527117194095"
    lpa = lpa_module.TiciLPA()

    monkeypatch.setattr(lpa, "_validate_profile_exists", lambda iccid: None)
    monkeypatch.setattr(lpa, "_ensure_switchable_profile", lambda iccid: None)
    monkeypatch.setattr(lpa, "get_active_profile", lambda: Profile("8901240527117113293", "US Mobile", True, "Wireless"))
    monkeypatch.setattr(lpa, "_wait_for_modem", lambda: None)
    monkeypatch.setattr(lpa, "_ensure_client", lambda: type("Client", (), {"channel": "2", "_use_csim": False})())
    monkeypatch.setattr(
      lpa,
      "list_profiles",
      lambda: [
        Profile("8901240527117113293", "US Mobile", False, "Wireless"),
        Profile(target_iccid, "T-Mobile", True, "Wireless"),
      ],
    )
    monkeypatch.setattr(lpa_module, "enable_profile", lambda client, iccid, refresh=True: None)
    monkeypatch.setattr(
      lpa_module,
      "process_notifications",
      lambda client: (_ for _ in ()).throw(RuntimeError('AT command failed (AT+CGLA=2,16,"80E2910003BF2800"): AT command failed')),
    )

    lpa.switch_profile(target_iccid)

  @pytest.mark.parametrize(("is_eg25", "expected_refresh", "expected_waits", "expected_reboots"), [
    (True, True, 1, 0),
    (False, False, 0, 1),
  ])
  def test_switch_profile_uses_modem_specific_refresh_behavior(self, monkeypatch, is_eg25, expected_refresh, expected_waits, expected_reboots):
    target_iccid = "8901240527117194095"
    lpa = object.__new__(lpa_module.TiciLPA)
    lpa._is_eg25 = is_eg25
    lpa.verbose = False

    waits = []
    reboots = []
    refresh_values = []

    monkeypatch.setattr(lpa, "_validate_profile_exists", lambda iccid: None)
    monkeypatch.setattr(lpa, "_ensure_switchable_profile", lambda iccid: None)
    monkeypatch.setattr(lpa, "get_active_profile", lambda: Profile("8901240527117113293", "US Mobile", True, "Wireless"))
    monkeypatch.setattr(lpa, "_wait_for_modem", lambda: waits.append(True))
    monkeypatch.setattr(lpa, "_restart_modem", lambda: reboots.append(True))
    monkeypatch.setattr(lpa, "_with_lpa_error", lambda fn: fn())
    monkeypatch.setattr(lpa, "_ensure_client", lambda: type("Client", (), {"channel": "2", "_use_csim": False})())
    monkeypatch.setattr(
      lpa,
      "_process_notifications_after_state_change",
      lambda validator, _recovery_message, _failure_message: validator(),
    )
    monkeypatch.setattr(
      lpa,
      "list_profiles",
      lambda: [
        Profile("8901240527117113293", "US Mobile", False, "Wireless"),
        Profile(target_iccid, "T-Mobile", True, "Wireless"),
      ],
    )

    def fake_enable_profile(client, iccid, refresh=True):
      refresh_values.append(refresh)

    monkeypatch.setattr(lpa_module, "enable_profile", fake_enable_profile)

    lpa.switch_profile(target_iccid)

    assert refresh_values == [expected_refresh]
    assert len(waits) == expected_waits
    assert len(reboots) == expected_reboots

  def test_download_ignores_notification_cleanup_if_profile_exists(self, monkeypatch):
    target_iccid = "8901240527117194095"
    lpa = lpa_module.TiciLPA()
    profiles = [
      [Profile("8901240527117113293", "US Mobile", True, "Wireless")],
      [
        Profile("8901240527117113293", "US Mobile", True, "Wireless"),
        Profile(target_iccid, "T-Mobile", False, "Wireless"),
      ],
      [
        Profile("8901240527117113293", "US Mobile", True, "Wireless"),
        Profile(target_iccid, "T-Mobile", False, "Wireless"),
      ],
    ]

    monkeypatch.setattr(lpa, "_ensure_client", lambda: object())
    monkeypatch.setattr(lpa, "_wait_for_modem", lambda: None)
    monkeypatch.setattr(lpa, "list_profiles", lambda: profiles.pop(0))
    monkeypatch.setattr(lpa_module, "download_profile", lambda client, qr: target_iccid)
    monkeypatch.setattr(
      lpa_module,
      "process_notifications",
      lambda client: (_ for _ in ()).throw(RuntimeError('AT command failed (AT+CGLA=2,16,"80E2910003BF2800"): AT command failed')),
    )

    lpa.download_profile(TEST_ACTIVATION_CODE, "T-Mobile")


class TestEsimManagerSupportGating:
  def test_refresh_profiles_does_not_touch_lpa_without_euicc(self, monkeypatch):
    manager = EsimManager()

    monkeypatch.setattr(manager, "_query_euicc_support", lambda: False)
    monkeypatch.setattr(manager._params, "get", lambda _key: None)
    monkeypatch.setattr(manager._params, "get_bool", lambda _key: True)
    monkeypatch.setattr(HARDWARE, "get_device_type", lambda: "tici")
    monkeypatch.setattr(HARDWARE, "get_sim_lpa", lambda: (_ for _ in ()).throw(AssertionError("LPA should not be touched")))

    manager.refresh_profiles()

    assert manager.get_state().profiles == []
    assert manager.get_state().message == "eSIM provisioning unavailable on this device"
