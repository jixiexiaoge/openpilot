# 与原厂功能的集成

在所有支持的车型中:
* 原厂车道保持辅助(LKA)和自动车道居中(ALC)功能会被openpilot的ALC取代,后者仅在用户启用openpilot时工作
* 原厂车道偏离警告(LDW)会被openpilot的LDW取代

此外,在特定支持的车型上(参见[支持的车型](CARS.md)中的ACC列):
* 原厂自适应巡航控制(ACC)会被openpilot的ACC取代
* openpilot的前向碰撞警告(FCW)会与原厂FCW一起工作

openpilot会保留车辆的其他原厂功能,包括但不限于:FCW、自动紧急制动(AEB)、自动远光灯、盲点警告和侧面碰撞警告。
