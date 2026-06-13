"""
Copyright ©️ IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

import base64
import json
import time
from enum import Enum
from typing import Any
from datetime import datetime

from openpilot.common.git import get_branch
from openpilot.common.params import Params, ParamKeyFlag
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.system.version import get_version

from cereal import messaging, custom
from iqpilot.konn3kt.api import Konn3ktApi
from iqpilot.konn3kt.backups.utils import decrypt_compressed_data, encrypt_compress_data, SnakeCaseEncoder
from iqpilot.konn3kt.common.params import param_to_bytes, param_from_base64

K3_LOG_FILE = "/data/openpilot/k3_log.txt"

def k3_log(msg: str):
  try:
    with open(K3_LOG_FILE, "a") as f:
      timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
      f.write(f"[{timestamp}] {msg}\n")
      f.flush()
  except Exception as e:
    cloudlog.error(f"[K3] Failed to write to debug log: {e}")

k3_log("=== K3 Backup Manager Module Loaded ===")


class OperationType(Enum):
  BACKUP = "backup"
  RESTORE = "restore"


class BackupManagerK3:

  def __init__(self):
    k3_log("BackupManagerK3 initializing...")
    self.params = Params()
    self.device_id = self.params.get("DongleId")
    k3_log(f"Device ID: {self.device_id}")
    self.api = Konn3ktApi(self.device_id)
    self.pm = messaging.PubMaster(["backupManagerK3"])

    self.backup_status = custom.IQBackupManager.Status.idle
    self.restore_status = custom.IQBackupManager.Status.idle

    self.progress = 0.0
    self.operation: OperationType | None = None

    self.last_error = ""
    k3_log("BackupManagerK3 initialized successfully")

  def _report_status(self) -> None:
    msg = messaging.new_message('backupManagerK3', valid=True)
    backup_state = msg.backupManagerK3

    backup_state.backupStatus = self.backup_status
    backup_state.restoreStatus = self.restore_status
    backup_state.backupProgress = self.progress
    backup_state.restoreProgress = self.progress
    backup_state.lastError = self.last_error

    self.pm.send('backupManagerK3', msg)

  def _update_progress(self, progress: float, op_type: OperationType) -> None:
    self.progress = progress
    self.operation = op_type
    self._report_status()

  def _collect_config_data(self) -> dict[str, Any]:
    config_data = {}
    params_to_backup = [k.decode('utf-8') for k in self.params.all_keys(ParamKeyFlag.BACKUP)]
    for param in params_to_backup:
      value = param_to_bytes(param)
      if value is not None:
        config_data[param] = base64.b64encode(value).decode('utf-8')
    return config_data

  def _get_metadata_value(self, metadata_list, key, default_value=None):
    return next((entry.get("value") for entry in metadata_list if entry.get("key") == key), default_value)

  async def create_backup(self) -> bool:
    k3_log("create_backup() called")
    try:
      k3_log("Setting status to inProgress")
      self.backup_status = custom.IQBackupManager.Status.inProgress
      self._update_progress(0.0, OperationType.BACKUP)

      k3_log("Collecting config data...")
      config_data = self._collect_config_data()
      k3_log(f"Collected {len(config_data)} params")
      self._update_progress(25.0, OperationType.BACKUP)

      k3_log("Encrypting config data...")
      config_json = json.dumps(config_data)
      encrypted_config = encrypt_compress_data(config_json, use_aes_256=True)
      k3_log(f"Encrypted config length: {len(encrypted_config)}")
      self._update_progress(50.0, OperationType.BACKUP)

      k3_log("Building backup info...")
      backup_info = custom.IQBackupManager.BackupInfo()
      backup_info.deviceId = self.device_id
      backup_info.config = encrypted_config
      backup_info.isEncrypted = True
      backup_info.createdAt = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
      backup_info.updatedAt = backup_info.createdAt
      backup_info.iqpilotVersion = self._get_current_version()
      backup_info.backupMetadata = [
        custom.IQBackupManager.MetadataEntry(key="creator", value="BackupManagerK3"),
        custom.IQBackupManager.MetadataEntry(key="all_values_encoded", value="True"),
        custom.IQBackupManager.MetadataEntry(key="AES", value="256")
      ]

      k3_log("Converting to payload...")
      payload = json.loads(json.dumps(backup_info.to_dict(), cls=SnakeCaseEncoder))
      self._update_progress(75.0, OperationType.BACKUP)

      k3_log(f"Uploading backup to api/v2/backup/{self.device_id}")
      cloudlog.debug(f"[K3] Uploading backup with payload: {json.dumps(payload)}")
      result = self.api.api_get(
        f"api/v2/backup/{self.device_id}",
        method='PUT',
        access_token=self.api.get_token(),
        json=payload
      )
      k3_log(f"API result: {result}")

      if result:
        k3_log("Backup upload successful!")
        self.backup_status = custom.IQBackupManager.Status.completed
        self._update_progress(100.0, OperationType.BACKUP)
        cloudlog.info("[K3] Backup successfully created and uploaded")
      else:
        k3_log(f"Backup upload failed: {result}")
        self.backup_status = custom.IQBackupManager.Status.failed
        self.last_error = "Failed to upload backup"
        cloudlog.error(f"[K3] {result}")
        self._report_status()

      return bool(self.backup_status == custom.IQBackupManager.Status.completed)

    except Exception as e:
      k3_log(f"Exception in create_backup: {type(e).__name__}: {str(e)}")
      import traceback
      k3_log(f"Traceback: {traceback.format_exc()}")
      cloudlog.exception(f"[K3] Error creating backup: {str(e)}")
      self.backup_status = custom.IQBackupManager.Status.failed
      self.last_error = str(e)
      self._report_status()
      return False

  async def restore_backup(self, version: int | None = None) -> bool:
    k3_log(f"restore_backup() called with version={version}")
    try:
      k3_log("Setting restore status to inProgress")
      self.restore_status = custom.IQBackupManager.Status.inProgress
      self._update_progress(0.0, OperationType.RESTORE)

      endpoint = f"api/v2/backup/{self.device_id}" + (f"/{version}" if version else "")
      k3_log(f"Fetching backup from endpoint: {endpoint}")
      backup_data = self.api.api_get(endpoint, access_token=self.api.get_token())
      k3_log(f"API response: {backup_data}")
      if not backup_data:
        raise Exception(f"No backup found for device {self.device_id}")

      self._update_progress(25.0, OperationType.RESTORE)

      data = backup_data.json()
      k3_log(f"Parsed JSON data, keys: {data.keys() if data else None}")
      backup_metadata = data.get("backup_metadata", [])
      encrypted_config = data.get("config", "")
      k3_log(f"Encrypted config length: {len(encrypted_config) if encrypted_config else 0}")
      if not encrypted_config:
        raise Exception("Empty backup configuration")
      self._update_progress(50.0, OperationType.RESTORE)

      use_aes_256 = self._get_metadata_value(backup_metadata, "AES", "128") == "256"
      k3_log(f"Using AES-256: {use_aes_256}")
      k3_log("Decrypting backup...")
      config_json = decrypt_compressed_data(encrypted_config, use_aes_256)
      k3_log(f"Decrypted config length: {len(config_json) if config_json else 0}")
      if not config_json:
        raise Exception("Failed to decrypt backup configuration")

      config_data = json.loads(config_json)
      k3_log(f"Parsed config data, {len(config_data)} params")
      self._update_progress(75.0, OperationType.RESTORE)

      k3_log("Applying configuration...")
      self._apply_config(config_data)

      k3_log("Restore completed successfully!")
      self.restore_status = custom.IQBackupManager.Status.completed
      self._update_progress(100.0, OperationType.RESTORE)
      cloudlog.info("[K3] Backup successfully restored")
      return True

    except Exception as e:
      k3_log(f"Exception in restore_backup: {type(e).__name__}: {str(e)}")
      import traceback
      k3_log(f"Traceback: {traceback.format_exc()}")
      cloudlog.exception(f"[K3] Error restoring backup: {str(e)}")
      self.restore_status = custom.IQBackupManager.Status.failed
      self.last_error = str(e)
      self._report_status()
      return False

  def _apply_config(self, config_data: dict[str, str]) -> None:
    backupable_params = [k.decode('utf-8') for k in self.params.all_keys(ParamKeyFlag.BACKUP)]
    backupable_set_lower = {p.lower() for p in backupable_params}

    restored_count = 0
    skipped_count = 0

    for param, encoded_value in config_data.items():
      if param.lower() in backupable_set_lower:
        real_param = next(p for p in backupable_params if p.lower() == param.lower())
        try:
          param_from_base64(real_param, encoded_value)
          restored_count += 1
        except Exception as e:
          cloudlog.error(f"[K3] Failed to restore param {param}: {str(e)}")
      else:
        skipped_count += 1
        cloudlog.info(f"[K3] Skipped restoring param {param}: not marked for backup in current version")

    cloudlog.info(f"[K3] Restore complete: {restored_count} params restored, {skipped_count} params skipped")

  def _get_current_version(self) -> custom.IQBackupManager.Version:
    version_obj = custom.IQBackupManager.Version()
    version_str = get_version()

    version_parts = version_str.split('-')
    version_nums = version_parts[0].split('.')

    build = 0
    if len(version_parts) > 1 and version_parts[1].isdigit():
      build = int(version_parts[1])
    elif len(version_nums) > 3 and version_nums[3].isdigit():
      build = int(version_nums[3])

    version_obj.major = int(version_nums[0]) if len(version_nums) > 0 and version_nums[0].isdigit() else 0
    version_obj.minor = int(version_nums[1]) if len(version_nums) > 1 and version_nums[1].isdigit() else 0
    version_obj.patch = int(version_nums[2]) if len(version_nums) > 2 and version_nums[2].isdigit() else 0
    version_obj.build = build
    version_obj.branch = get_branch()

    return version_obj

  async def main_thread(self) -> None:
    k3_log("main_thread() starting")
    rk = Ratekeeper(1, print_delay_threshold=None)
    reset_progress = False

    k3_log("Entering main loop")
    while True:
      try:
        if reset_progress:
          self.progress = 100.0
          self.operation = None
          self.restore_status = custom.IQBackupManager.Status.idle
          self.backup_status = custom.IQBackupManager.Status.idle

        create_backup_param = self.params.get_bool("BackupManagerK3_CreateBackup")
        if create_backup_param:
          k3_log(f"Detected BackupManagerK3_CreateBackup = {create_backup_param}")
          try:
            if await self.create_backup():
              k3_log("create_backup() returned True")
              reset_progress = True
            else:
              k3_log("create_backup() returned False")
          finally:
            k3_log("Removing BackupManagerK3_CreateBackup param")
            self.params.remove("BackupManagerK3_CreateBackup")

        restore_version = self.params.get("BackupManagerK3_RestoreVersion")
        if restore_version:
          k3_log(f"Detected BackupManagerK3_RestoreVersion = {restore_version}")
          k3_log(f"Type: {type(restore_version)}, Value: {repr(restore_version)}")
          try:

            version_str = restore_version.decode('utf-8') if isinstance(restore_version, bytes) else restore_version
            k3_log(f"Converted version string: {version_str}")
            version = int(version_str) if version_str.isdigit() else None
            k3_log(f"Parsed version number: {version}")
            k3_log("Calling restore_backup()...")
            result = await self.restore_backup(version)
            k3_log(f"restore_backup() returned: {result}")
            reset_progress = True
          except Exception as e:
            k3_log(f"Exception during restore: {type(e).__name__}: {str(e)}")
            import traceback
            k3_log(f"Traceback: {traceback.format_exc()}")
          finally:
            k3_log("Removing BackupManagerK3_RestoreVersion param")
            self.params.remove("BackupManagerK3_RestoreVersion")

        self._report_status()
        rk.keep_time()

      except Exception as e:
        k3_log(f"Exception in main_thread: {type(e).__name__}: {str(e)}")
        import traceback
        k3_log(f"Traceback: {traceback.format_exc()}")
        cloudlog.exception(f"[K3] Error in backup manager main thread: {str(e)}")
        self.last_error = str(e)
        self._report_status()
        rk.keep_time()


def main():
  k3_log("main() function called, starting BackupManagerK3")
  import asyncio
  asyncio.run(BackupManagerK3().main_thread())


if __name__ == "__main__":
  main()