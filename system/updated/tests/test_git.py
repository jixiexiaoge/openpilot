import contextlib
import os
from openpilot.system.updated.tests.test_base import ParamsBaseUpdateTest, run, update_release
from openpilot.system.updated.updated import cleanup_stale_prebuilt_marker


class TestUpdateDGitStrategy(ParamsBaseUpdateTest):
  def update_remote_release(self, release):
    update_release(self.remote_dir, release, *self.MOCK_RELEASES[release])
    run(["git", "add", "."], cwd=self.remote_dir)
    run(["git", "commit", "-m", f"openpilot release {release}"], cwd=self.remote_dir)

  def setup_remote_release(self, release):
    run(["git", "init"], cwd=self.remote_dir)
    run(["git", "checkout", "-b", release], cwd=self.remote_dir)
    self.update_remote_release(release)

  def setup_basedir_release(self, release):
    super().setup_basedir_release(release)
    run(["git", "clone", "-b", release, self.remote_dir, self.basedir])

  @contextlib.contextmanager
  def additional_context(self):
    yield

  def test_cleanup_stale_prebuilt_marker(self):
    self.setup_remote_release("release3")
    self.setup_basedir_release("release3")

    prebuilt_path = os.path.join(self.basedir, "prebuilt")
    with open(prebuilt_path, "w") as f:
      f.write("")

    cleanup_stale_prebuilt_marker(str(self.basedir), "release3")
    assert not os.path.exists(prebuilt_path)

  def test_keep_prebuilt_marker_for_prebuilt_branch(self):
    self.setup_remote_release("release3")
    self.setup_basedir_release("release3")

    prebuilt_path = os.path.join(self.basedir, "prebuilt")
    with open(prebuilt_path, "w") as f:
      f.write("")

    cleanup_stale_prebuilt_marker(str(self.basedir), "release3-prebuilt")
    assert os.path.exists(prebuilt_path)
