# Mazda CX-5 (2022) CAN 信号分析

本文档基于 `opendbc/car/mazda/` 下的 `carstate.py`, `carcontroller.py`, `mazdacan.py` 代码逆向分析整理，主要适用于 **Mazda CX-5 2022 (Gen1 Hardware)** 及兼容车型。

## 1. 信号交互总表

下表列出了 Openpilot 针对 Mazda 车型读取（Rx）和发送（Tx）的主要 CAN 消息，包含从 `safety_mazda.h` 提取的 16 进制 ID。

| Message Name (DBC) | ID (Hex) | 信号名称 | 方向 | 详情/逻辑 | 代码逻辑/备注 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **WHEEL_SPEEDS** | **0x215** | `FL`, `FR`, `RL`, `RR` | Rx | **单位**: km/h (原始值)<br>**用途**: 计算车速 | `ret.vEgoRaw = (fl+fr+rl+rr)/4` |
| **STEER** | **0x082** | `STEER_ANGLE` | Rx | **单位**: deg (度) | `ret.steeringAngleDeg` |
| **MAZDA_STEER_TORQUE** | **0x240** | `STEER_TORQUE_SENSOR` | Rx | **用途**: 驾驶员手力<br>**Offset**: -127 | `update_sample(&torque_driver, val - 127)` |
| **MAZDA_PEDALS** | **0x165** | `BRAKE_ON` | Rx | **值**: 0/1 | `brake_pressed = val & 0x10` |
| **MAZDA_ENGINE_DATA**| **0x202** | `PEDAL_GAS` | Rx | - | `gas_pressed = val > 0` |
| **MAZDA_ENGINE_DATA**| **0x202** | `SPEED` | Rx | **Factor**: 0.01 | `vehicle_moving = speed > 10` |
| **MAZDA_CRZ_BTNS** | **0x09D** | `SET_P/M`, `RES`, `CAN_OFF` | Rx/Tx | **用途**: 巡航按键<br>**信号**: 含反转位 (INV) | 包含 `SET_P`, `SET_M`, `RES`, `CAN_OFF`, `DISTANCE_...` 等及其反逻辑校验位 |
| **MAZDA_CRZ_CTRL** | **0x21C** | `CRZ_ACTIVE` | Rx | **值**: 1 (激活) | `pcm_cruise_check(val & 0x8)` |
| **MAZDA_LKAS** | **0x243** | `LKAS_REQUEST` | **Tx** | **范围**: +/- 800 | 阻断 Camera 的 0x243，发送 OP 的指令 |
| **MAZDA_LKAS_HUD** | **0x440** | `HANDS_WARN_...` | **Tx** | **用途**: HUD 警告 | 阻断 Camera 的 0x440，发送 OP 的警告 |

## 2. Mazda 专属逻辑详解

### 2.1 横向控制 (Steering) - `CAM_LKAS`
Mazda 的横向控制具有非常明显的 "中间人" (MITM) 特征。Openpilot 会读取 Camera 发出的数据，修改其中的 Torque 请求，然后重新计算校验和发送给 EPS。

*   **控制 ID**: `CAM_LKAS` (在 DBC 中通常对应 `0x240` 附近，视具体车型而定)。
*   **扭矩计算**:
    ```python
    # 0 扭矩对应 2048 (0x800)
    tmp = apply_torque + 2048
    lo = tmp & 0xFF
    hi = tmp >> 8
    ```
*   **校验和 (Checksum) 算法**:
    Mazda 使用了一个特殊的模 256 减法校验与位移逻辑，包含与计数器、状态位及转向角的复杂运算。
    ```python
    # 基础公式
    csum = 249 - ctr - hi - lo - (lnv << 3) - er1 - (ldw << 7) - (er2 << 4) - (b1 << 5)
    # 包含转向角的高位处理
    csum = csum - ahi - amd - alo - b2
    if ahi == 1: csum = csum + 15
    # 归一化到 0-255
    if csum < 0: ...
    csum = csum % 256
    ```
*   **Pass-through 逻辑**:
    OP 在发送控制指令时，必须原样转发原车 Camera 的状态位（如 `ERR_BIT_1`, `LINE_NOT_VISIBLE`, `LDW` 等），否则 EPS 会报故障。代码中通过 `cp_cam.vl["CAM_LKAS"]` 获取这些值并在 `create_steering_control` 中透传。

### 2.2 纵向/巡航控制 - `CRZ_BTNS`
Openpilot 并不直接控制 Mazda 的油门/刹车（针对此代码版本），而是通过**模拟方向盘按键**来控制原车的 ACC 系统。

*   **控制 ID**: `CRZ_BTNS` (**0x09D**).
*   **信号定义 (DBC)**:
    *   **控制位**: `SET_P` (Set+), `SET_M` (Set-), `RES` (Resume), `CAN_OFF` (Cancel)。
    *   **距离/模式**: `DISTANCE_LESS`, `DISTANCE_MORE`, `MODE_X`, `MODE_Y`。
    *   **校验与反逻辑**: 每个控制信号都有一个对应的 `_INV` 信号（如 `SET_P_INV`）。Mazda 要求主信号与反转信号必须互斥（例如 `SET_P=1` 则 `SET_P_INV=0`），否则 ECU 会报错。
    *   **固定位**: `BIT1`, `BIT2`, `BIT3` 通常置为 1。
*   **Spam Button (模拟加减速)**:
    由于 Openpilot 无法直接控制 Mazda 的油门和刹车踏板（通过 PCM 巡航控制），它通过快速连续发送巡航按键来调整巡航设定速度，从而间接控制车辆的加速和减速。
    *   **加速 (Acceleration)**: 当 OP 期望速度 (`Target`) 高于当前巡航速度 (`Current`) 时，`make_spam_button` 会发送 `SET_PLUS` 按钮。这会提高原车 ACC 的设定目标，促使 ECU 控制油门加速。
    *   **减速 (Deceleration)**: 当 OP 期望速度 (`Target`) 低于当前巡航速度 (`Current`) 时，`make_spam_button` 会发送 `SET_MINUS` 按钮。这会降低原车 ACC 的设定目标，促使 ECU 控制刹车或利用发动机制动减速。
    *   **限制条件**: 代码中存在一些安全限制，例如当前速度 >= 31kph 时才允许发送减速指令（防止在低速下意外解除巡航），最高设定速度被限制在 160kph 以下。
    *   **Resume Logic**: Mazda 具有 "Stop and Go" 功能，但停车超过 3 秒后需手动按 RES 或踩油门。OP 检测到 `standstill` 且需移动时，会自动发送 `RESUME` 按钮。
    *   **Cancel Logic**: 当 `CC.cruiseControl.cancel` 为真时，发送 `CANCEL` 按钮。

### 2.3 HUD 警报 (Alerts)
*   **消息**: `CAM_LANEINFO` (在安全代码中定义为 `MAZDA_LKAS_HUD` 0x440)。
*   **逻辑**: 通过操作 `HANDS_WARN_3_BITS` 和 `HANDS_ON_STEER_WARN` 位来触发仪表盘的 "请接管方向盘" 警告。
    *   `steer_required = True` -> `HANDS_WARN_3_BITS` 置为 `111` (二进制 7)。
    *   `ldw = True` -> 触发 LDW 警告位。
*   **注意事项**: 代码中注释提到目前的模拟方式可能会伴随原车的蜂鸣声，这在 Openpilot 的体验中可能是一个需要优化的点（"silence audible warnings"）。

### 2.4 安全与限制参数 (Safety & Tuning)
基于 `values.py` 和 `safety_mazda.h` 的定义，Mazda 平台的控制参数如下：

*   **转向扭矩限制**:
    *   **最大力矩**: `800` (原始单位, 对应 `STEER_MAX`)。
    *   **力矩变化率**:
        *   增扭 (Up): `10` (每10ms, 较慢以保证平顺)。
        *   减扭 (Down): `25` (每10ms, 允许快速卸力)。
    *   **驾驶员对抗**: 允许 `15` 单位的驾驶员输入误差 (`STEER_DRIVER_ALLOWANCE`)。
*   **0 MPH 转向支持**:
    *   对于 **CX-5 2022** 车型，`interface.py` 中特意**未**设置 `minSteerSpeed` (默认为 0)，这表明 OP 在该车型上尝试支持静止状态下的转向控制 (0 MPH Steer)。
    *   其他 Mazda 车型通常限制在 `45 kph` (`LKAS_LIMITS.DISABLE_SPEED`) 下退出 LKAS。

## 3. "既接收又发送" (MITM) 信号分析

Openpilot 在 Mazda 车型上通过截断原车前视摄像头 (FSC, Forward Sensing Camera) 与 PT CAN 总线的连接来实现控制。这种架构被称为 "Man-In-The-Middle" (中间人) 模式。

### 3.1 硬件拓扑与拦截
*   **连接位置**: 位于前挡风玻璃处的 FSC 摄像头模块接口。
*   **总线定义**:
    *   **Bus 0 (PT/Main)**: 连接车辆主要动力系统（EPS, 引擎, 仪表盘等）。
    *   **Bus 2 (Cam)**: 连接被断开的 FSC 摄像头。
*   **数据流向**: `[FSC 摄像头] (Bus 2) <==> [Openpilot] <==> [车辆 PT 网络] (Bus 0)`

### 3.2 转发与阻断规则 (Forwarding Policy)
根据 `safety_mazda.h` 中的 `mazda_fwd_hook` 定义：

1.  **Main (Bus 0) -> Cam (Bus 2)**:
    *   **全量转发**: 所有的车辆状态信息（车速、轮速、方向盘角度、驾驶员操作等）都会毫无保留地转发给摄像头。这保证了 FSC 摄像头认为自己仍连接在车辆上，不会报通讯丢失故障。

2.  **Cam (Bus 2) -> Main (Bus 0)**:
    *   **选择性阻断 (Block)**: 仅阻断以下两个关键 ID，防止原车摄像头的控制指令干扰 Openpilot。
        *   `0x243` (**MAZDA_LKAS**): 原车的车道保持力矩请求。
        *   `0x440` (**MAZDA_LKAS_HUD**): 原车的车道线显示与报警指令。
    *   **透传 (Forward)**: 其他所有报文（如交通标志识别、FSC 自身状态等）均予以通过，保留原车其他辅助功能正常工作。

### 3.3 信号篡改策略 (Spoofing & Injection)

| 信号类型 | Message ID | 篡改方式 | 详细逻辑分析 |
| :--- | :--- | :--- | :--- |
| **MITM 替换** | `0x243` (LKAS) | **读取-修改-发送** | **状态透传 + 扭矩重写**: <br> OP 读取 Bus 2 上 FSC 发出的 0x243 报文，提取其中的状态位（如 `ERR_BIT_1`, `LINE_NOT_VISIBLE` 等错误标志），将其**原样复制**到新报文中。 <br> **控制接管**: 仅将原来的 Torque (转向力矩) 字段替换为 Openpilot 计算的 `apply_torque`，然后重新计算 Checksum 发送到 Bus 0。这意味着 EPS 看到的“状态”来自原厂摄像头，“指令”来自 OP。 |
| **MITM 替换** | `0x440` (HUD) | **读取-修改-发送** | **感知透传 + 报警重写**: <br> OP 读取 Bus 2 上的原始车道线信息（`LANE_LINES`），保留原车摄像头对车道线的视觉识别结果（这使得仪表盘上的车道线显示仍然准确）。 <br> **报警接管**: 修改 `HANDS_WARN` 等位，根据 OP 的状态触发 "手扶方向盘" 警告，融合了原车的视觉显示与 OP 的交互逻辑。 |
| **纯注入** | `0x09D` (Buttons)| **直接注入** | **模拟点击**: <br> 此信号并非来自 Camera (Bus 2)，而是 OP 作为一个额外的设备直接向 Bus 0 发送。 <br> 当 OP 需要调整巡航速度时，会发送模拟的按键帧。为了防止与原车物理按键（如果在 Bus 0 上）冲突，OP 通常利用总线空闲或特定的时序进行注入，且依赖 `safety_mazda.h` 中的检查确保安全性。 |

### 3.4 关键技术细节
*   **Checksum 算法**: Mazda 的 Checksum 算法 (Mod 256) 比较特殊，不仅依赖 Payload，还经常与 `Counter` 甚至 `Static Offset` 挂钩。OP 必须精确复现此算法（见 `mazdacan.py`），否则 EPS 会拒绝响应。
*   **Counter 同步**: 对于 MITM 信号，OP 通常会延续原车摄像头的 Counter 序列，或者基于自己的时钟生成（如 Mazda 代码中看起来使用了 `frame % 16` 自行生成 Counter，而不是透传原有 Counter，这需要确保频率与原车一致以免超时）。
