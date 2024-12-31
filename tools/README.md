# openpilot工具集

## 系统要求

openpilot在**Ubuntu 24.04**上开发和测试,这是除了[支持的嵌入式硬件](https://github.com/commaai/openpilot#running-on-a-dedicated-device-in-a-car)之外的主要开发目标平台。

不建议在其他系统上原生运行,这需要进行修改。在Windows上可以使用WSL,在macOS或不兼容的Linux系统上建议使用开发容器。

## Ubuntu 24.04原生环境搭建

**1. 克隆openpilot**

注意:本仓库使用Git LFS存储大文件。在克隆或使用前请确保已安装并配置[Git LFS](https://git-lfs.com/)。

可以进行部分克隆以加快下载:
``` bash
git clone --filter=blob:none --recurse-submodules --also-filter-submodules https://github.com/commaai/openpilot.git
```

或者进行完整克隆:
``` bash
git clone --recurse-submodules https://github.com/commaai/openpilot.git
```

**2. 运行安装脚本**

``` bash
cd openpilot
tools/ubuntu_setup.sh
```

**3. 拉取Git LFS文件**

``` bash
git lfs pull
```

**4. 激活Python环境**

激活已安装Python依赖的环境:
``` bash
source .venv/bin/activate
```

**5. 编译openpilot**

``` bash
scons -u -j$(nproc)
```

## 在Linux或macOS上使用开发容器

openpilot支持[Dev Containers](https://containers.dev/). Dev containers提供可定制和一致的开发环境,包裹在容器中。这意味着您可以在与主要开发目标匹配的环境中开发,无论您的本地设置如何。

Dev containers支持[多个编辑器和IDE](https://containers.dev/supporting),包括Visual Studio Code。使用以下[指南](https://code.visualstudio.com/docs/devcontainers/containers)开始使用它们与VSCode。

#### X11转发在macOS上

GUI应用程序如`ui`或`cabana`也可以在容器中运行,通过利用X11转发。要在macOS上使用它,必须进行额外的配置步骤。按照[这些步骤](https://gist.github.com/sorny/969fe55d85c9b0035b0109a31cbcb088)设置X11转发。

## WSL在Windows上

[Windows Subsystem for Linux (WSL)](https://docs.microsoft.com/en-us/windows/wsl/about)应该提供与原生Ubuntu类似的体验。[WSL 2](https://docs.microsoft.com/en-us/windows/wsl/compare-versions)特别被许多用户报告为无缝体验。

按照[这些说明](https://docs.microsoft.com/en-us/windows/wsl/install)设置WSL并安装`Ubuntu-24.04`分布。一旦您的Ubuntu WSL环境设置好,按照Linux设置说明完成设置环境。查看[这些说明](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps)运行GUI应用程序。

**注意**:如果您在运行WSL并且任何GUI失败(段错误或其他奇怪的问题)即使按照上述步骤,您可能需要启用软件渲染,例如`LIBGL_ALWAYS_SOFTWARE=1`,例如`LIBGL_ALWAYS_SOFTWARE=1 selfdrive/ui/ui`。

## CTF

了解openpilot生态系统和工具,通过玩我们的[CTF](/tools/CTF.md)。

## 目录结构

```
├── ubuntu_setup.sh     # Ubuntu系统的安装脚本
├── mac_setup.sh        # macOS系统的安装脚本
├── cabana/             # 实时查看和绘制CAN消息
├── camerastream/       # 通过网络进行摄像头流传输
├── joystick/          # 使用游戏手柄控制车辆
├── lib/               # 支持工具和读取openpilot日志的库
├── plotjuggler/       # openpilot日志绘图工具
├── replay/            # 回放驾驶数据和模拟openpilot服务
├── scripts/           # 各种实用脚本
├── serial/            # comma串口工具
├── sim/               # 在模拟器中运行openpilot
└── webcam/            # 在PC上使用网络摄像头运行openpilot
```
