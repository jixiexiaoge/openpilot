"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from cereal import messaging, custom

if __name__ == "__main__":
  sm = messaging.SubMaster(["iqModelManager"])
  while True:
    sm.update(500)
    if sm.updated:
      msg = sm["iqModelManager"]
      for model in msg.selectedBundle.models:
        if model.downloadProgress.status == custom.IQModelManager.DownloadStatus.downloading:
          print("")
          print(f"{model.fileName}: {model.downloadProgress}")
          print("")
