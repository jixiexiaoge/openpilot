# 路线图

这是openpilot下一个主要版本的路线图。另请查看:

* [里程碑](https://github.com/commaai/openpilot/milestones) - 次要版本发布
* [项目](https://github.com/commaai/openpilot/projects?query=is%3Aopen) - 不与发布绑定的短期项目
* [悬赏任务](https://comma.ai/bounties) - 付费的个人任务
* Discord中的[#current-projects](https://discord.com/channels/469524606043160576/1249579909739708446) - 讨论正在进行的项目

## openpilot 0.10版本

openpilot 0.10将是第一个在[学习型模拟器](https://youtu.be/EqQNZXqzFSI)中训练驾驶策略的版本。

* 在学习型模拟器中训练的驾驶模型
* 始终开启的驾驶员监控(可通过开关控制)
* 从驾驶栈中移除GPS
* 100KB大小的qlogs
* 经过1000小时硬件在环测试后推送的`master-ci`
* 将车辆接口代码移至[opendbc](https://github.com/commaai/opendbc)
* 支持在Linux x86、Linux arm64和Mac(Apple Silicon)上运行openpilot

## openpilot 1.0版本

openpilot 1.0将实现完全端到端的驾驶策略。

* Chill模式下的端到端纵向控制
* 自动紧急制动(AEB)
* 带睡眠检测的驾驶员监控
* 由CI推送的滚动更新/发布
* [panda安全1.0](https://github.com/orgs/commaai/projects/27)
