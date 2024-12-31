## LogReader(日志读取器)

Route是一个用于方便访问你的路线中所有[日志](/system/loggerd/)的类。LogReader类用于读取非视频日志,即rlog.bz2和qlog.bz2文件。还有一个对应的FrameReader类用于读取视频。

```python
from openpilot.tools.lib.route import Route
from openpilot.tools.lib.logreader import LogReader

r = Route("a2a0ccea32023010|2023-07-27--13-01-19")

# 获取路线的rlog文件路径列表
print(r.log_paths())

# 获取前向摄像头(fcamera.hevc)文件路径
print(r.camera_paths())

# 设置LogReader来读取路线的第一个rlog
lr = LogReader(r.log_paths()[0])

# 打印日志中的所有消息
import codecs
codecs.register_error("strict", codecs.backslashreplace_errors)
for msg in lr:
  print(msg)

# 设置LogReader来读取路线的第二个qlog
lr = LogReader(r.log_paths()[1])

# 打印日志中的所有转向角度值
for msg in lr:
  if msg.which() == "carState":
    print(msg.carState.steeringAngleDeg)
```

### 片段范围

我们还支持一种称为"片段范围"的新格式:

```
344c5c15b34f2d8a   /   2024-01-03--09-37-12   /     2:6    /       q
[   设备ID        ] [       时间戳           ] [ 选择器  ]  [ 查询类型]
```

你可以指定要加载路线中的哪些片段:

```python
lr = LogReader("a2a0ccea32023010|2023-07-27--13-01-19/4")   # 第4个片段
lr = LogReader("a2a0ccea32023010|2023-07-27--13-01-19/4:6") # 第4和第5个片段
lr = LogReader("a2a0ccea32023010|2023-07-27--13-01-19/-1")  # 最后一个片段
lr = LogReader("a2a0ccea32023010|2023-07-27--13-01-19/:5")  # 前5个片段
lr = LogReader("a2a0ccea32023010|2023-07-27--13-01-19/1:")  # 除第一个外的所有片段
```

还可以选择要获取的日志类型:

```python
lr = LogReader("a2a0ccea32023010|2023-07-27--13-01-19/4/q") # 获取qlogs
lr = LogReader("a2a0ccea32023010|2023-07-27--13-01-19/4/r") # 获取rlogs(默认)
```
