from openpilot.common.params import Params
from openpilot.system.version import BuildMetadata, OpenpilotMetadata
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


def test_non_git_baked_deployment_uses_build_metadata(mocker):
  mocker.patch("openpilot.system.updated.updated.has_git_repo", return_value=False)
  mocker.patch("openpilot.system.updated.updated.HARDWARE.get_device_type", return_value="tici")
  mocker.patch(
    "openpilot.system.updated.updated.get_build_metadata",
    return_value=BuildMetadata(
      "release3",
      OpenpilotMetadata(
        version="1.2.3",
        release_notes="notes",
        git_commit="abcdef1234567890",
        git_origin="github.com/IQLvbs/openpilot",
        git_commit_date="Jul 02",
        build_style="release",
        is_dirty=False,
      ),
    ),
  )

  updater = Updater()

  assert updater.git_mode is False
  assert updater.get_branch() == "release3"
  assert updater.get_commit_hash() == "abcdef1234567890"
  assert updater.target_branch == "release3"
  assert updater.update_available is False
  assert updater.update_ready is False
