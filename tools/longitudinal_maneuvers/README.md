# 纵向机动测试

这是一个通过回放驾驶数据和运行测试来帮助调整纵向控制器的工具。

## 设置

首先,[设置你的PC环境](../../README.md)。

## 使用方法

### 记录驾驶数据

记录一些包含良好加速和制动事件的驾驶数据。机动测试工具会自动找到这些事件。

### 运行测试

```bash
# 运行所有测试
PYTHONPATH=/path/to/openpilot/ python test_longitudinal.py <路线名称>

# 运行特定测试
PYTHONPATH=/path/to/openpilot/ python test_longitudinal.py <路线名称> --test=acceleration
```

### 查看结果

```bash
cd /path/to/openpilot/tools/plotjuggler
./juggle.py --layout maneuvers.xml <测试结果文件>
```

## 测试项目

### 加速测试

该测试查找车辆从停止或低速开始加速的情况。它验证:

* 合理的加速时间
* 不超过目标速度
* 平滑加速(无抖动)

### 制动测试

该测试查找车辆制动至停止或降低速度的情况。它验证:

* 合理的制动距离
* 不超过目标速度
* 平滑减速(无抖动)

### 前车距离控制

该测试查找车辆跟随前车的情况。它验证:

* 保持安全跟车距离
* 平滑加速和制动
* 速度和距离无振荡
