# 什么是车型适配?

车型适配使openpilot能够支持特定的车型。每个openpilot支持的车型都需要单独进行适配。适配的复杂程度取决于多个因素,包括:

* 类似车型是否已有openpilot支持
* 车辆的架构和可用API


# 车型适配的结构

几乎所有特定车型的代码都包含在两个其他仓库中:[opendbc](https://github.com/commaai/opendbc)和[panda](https://github.com/commaai/panda)。

## opendbc仓库

每个汽车品牌都通过`opendbc/car/[brand]`中的标准接口结构支持:

* `interface.py`: 车辆接口,定义CarInterface类
* `carstate.py`: 读取车辆CAN消息并构建openpilot CarState消息
* `carcontroller.py`: 在车辆上执行openpilot CarControl动作的控制逻辑
* `[brand]can.py`: 为carcontroller组装要发送的CAN消息
* `values.py`: 执行器限制、车辆通用常量和支持的车型文档
* `radar_interface.py`: 解析车辆雷达点的接口(如果适用)

## panda

* `board/safety/safety_[brand].h`: 品牌特定的安全逻辑
* `tests/safety/test_[brand].py`: 品牌特定的安全CI测试

## openpilot

由于历史原因,openpilot仍然包含少量特定车型的逻辑代码。这些代码最终会迁移到opendbc或被移除。

* `selfdrive/car/car_specific.py`: 品牌特定的事件逻辑

# 概述

[Jason Young](https://github.com/jyoung8607)在COMMA_CON大会上做了关于车型适配流程的概述演讲。演讲视频可在YouTube上观看:

https://www.youtube.com/watch?v=XxPS5TpTUnI
