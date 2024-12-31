# 日志记录

openpilot将routes记录为一分钟长的片段(segments)。一个route从点火开始到熄火结束。

查看我们的[Python库](https://github.com/commaai/openpilot/blob/master/tools/lib/logreader.py)来读取openpilot日志。也可以使用我们的[工具](https://github.com/commaai/openpilot/tree/master/tools)来回放和查看数据。这些都是我们用于调试和开发openpilot的工具。

对于每个segment,openpilot记录以下类型的日志:

## rlog.bz2

rlogs包含openpilot进程之间传递的所有消息。查看[cereal/services.py](https://github.com/commaai/cereal/blob/master/services.py)获取所有记录的服务列表。它们是序列化的capnproto消息的bzip2压缩包。

## {f,e,d}camera.hevc

每个摄像头流都使用H.265编码并写入相应的文件。

* `fcamera.hevc` 是前向道路摄像头
* `ecamera.hevc` 是广角道路摄像头
* `dcamera.hevc` 是驾驶员监控摄像头

## qlog.bz2 & qcamera.ts

qlogs是rlogs的抽样子集。查看[cereal/services.py](https://github.com/commaai/cereal/blob/master/services.py)了解抽样详情。

qcameras是fcamera.hevc的H.264编码低分辨率版本。[comma connect](https://connect.comma.ai/)中显示的视频来自qcameras。

qlogs和qcameras的设计目标是文件足够小,可以在慢速网络下快速上传并永久存储,同时对大多数分析和调试工作来说仍然够用。
