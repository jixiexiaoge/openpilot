# openpilot模拟器
=====================

openpilot实现了一个[桥接器](bridge.py),使其能够在[CARLA模拟器](https://carla.org/)中运行。

## 运行模拟器
首先,启动CARLA服务器。更多信息请参见[CARLA快速入门指南](https://carla.readthedocs.io/en/latest/start_quickstart/)。

运行模拟器有以下几种方式:

### 方法1: Docker容器

```bash
# 获取模拟器
docker pull ghcr.io/commaai/carla:3.11.4

# 启动模拟器
docker run -it --net=host ghcr.io/commaai/carla:3.11.4 /bin/bash ./CarlaUE4.sh -opengl -nosound -quality-level=Low
```

### 方法2: 预编译二进制文件

下载[最新版本](https://github.com/commaai/carla/releases)并解压到本地。

```bash
# Ubuntu
./CarlaUE4.sh -opengl -nosound -quality-level=Low
```

### 方法3: 从源码构建

更多信息请参见[CARLA构建说明](https://carla.readthedocs.io/en/latest/build_linux/)。

## 运行openpilot

运行桥接器和openpilot:

```bash
# Terminal 1
cd tools/sim
./launch_openpilot.sh

# Terminal 2
./bridge.py
```

在另一个终端中,你可以使用以下命令控制模拟:

```bash
# 重新开始模拟
python replay/simulation_control.py --reset

# 切换到手动控制模式
python replay/simulation_control.py --mode=1

# 切换到openpilot控制模式
python replay/simulation_control.py --mode=2
```

该脚本还实现了以下可选参数:

```
  -h, --help            显示帮助信息并退出
  --host HOST           CARLA主机地址
  --port PORT           CARLA端口
  --tm-port TM_PORT     交通管理器端口
  --town TOWN           小镇名称
  --weather WEATHER     天气预设
  --vehicle VEHICLE     车辆类型
  --spawn SPAWN         生成点序号
  --mode MODE           驾驶模式(1-手动,2-自动)
  --list               列出可用的生成点
  --list-vehicles      列出可用的车辆类型
  --list-weathers      列出可用的天气预设
  --list-towns         列出可用的小镇
  --random-spawn       随机选择生成点
  --reset              重置模拟
```