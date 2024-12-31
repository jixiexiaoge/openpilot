# 游戏手柄控制

**所需硬件**: 运行openpilot的设备、笔记本电脑、游戏手柄(可选)

通过joystick_control,你可以通过网络将笔记本电脑连接到comma设备,并使用游戏手柄或键盘进行控制调试。
joystick_control使用[inputs](https://pypi.org/project/inputs)库,支持许多常见的游戏手柄和操纵杆。

## 使用方法

在启动`joystick_control`之前,汽车必须关闭,且openpilot必须处于offroad状态。

### 使用键盘

SSH连接到你的comma设备并使用以下命令启动joystick_control:

```shell
tools/joystick/joystick_control.py --keyboard
```

将显示可用的按键映射。通常,WASD键以5%的增量控制油门、制动和转向力矩。

### 在comma three上使用游戏手柄

将游戏手柄插入comma three的辅助USB-C端口。然后,SSH连接到设备并启动`joystick_control.py`。

### 在笔记本电脑上使用游戏手柄

要通过网络使用游戏手柄,我们需要在笔记本电脑上本地运行joystick_control,并让它通过网络向comma设备发送`testJoystick`数据包。

1. 将游戏手柄连接到电脑。
2. 将笔记本电脑连接到comma设备的热点并打开新的SSH连接。由于joystick_control在笔记本电脑上运行,我们需要写入一个参数让controlsd知道要在游戏手柄调试模式下启动:
   ```shell
   # 在comma设备上
   echo -n "1" > /data/params/d/JoystickDebugMode
   ```
3. 使用笔记本电脑的IP地址运行bridge。这会转发从笔记本电脑发送的`testJoystick`数据包,以便openpilot可以接收:
   ```shell
   # 在comma设备上
   cereal/messaging/bridge {LAPTOP_IP} testJoystick
   ```
4. 在笔记本电脑上以ZMQ模式启动joystick_control。
   ```shell
   # 在笔记本电脑上
   export ZMQ=1
   tools/joystick/joystick_control.py
   ```

---
现在启动你的车,openpilot应该会在启动时进入游戏手柄模式并显示提示!轴的状态会显示在提示中,而按钮状态会打印在shell中。

确保满足panda中允许控制的条件(例如巡航控制已启用)。你也可以修改panda代码以始终允许控制。

![](https://github.com/commaai/openpilot/assets/8762862/e640cbca-cb7a-4dcb-abce-b23b036ad8e7)
