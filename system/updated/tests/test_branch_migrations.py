from openpilot.common.params import Params
from openpilot.system.updated.updated import Updater


def test_tici_branch_migration(mocker):
  params = Params()
  params.put("UpdaterTargetBranch", "master-dev")
  mocker.patch("openpilot.system.updated.updated.HARDWARE.get_device_type", return_value="tici")

  try:
    assert Updater().target_branch == "master-mici-tici"
  finally:
    params.remove("UpdaterTargetBranch")


def test_non_tici_branch_unchanged(mocker):
  params = Params()
  params.put("UpdaterTargetBranch", "master-dev")
  mocker.patch("openpilot.system.updated.updated.HARDWARE.get_device_type", return_value="tizi")

  try:
    assert Updater().target_branch == "master-dev"
  finally:
    params.remove("UpdaterTargetBranch")
