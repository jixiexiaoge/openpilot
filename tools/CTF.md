## CTF(夺旗挑战赛)
欢迎来到comma CTF的第一部分!

* 所有的flag都在这个路线中: `0c7f0c7f0c7f0c7f|2021-10-13--13-00-00`
* 每个片段中有2个flag,难度逐渐增加
* 找到flag所需的所有工具都在openpilot仓库中
  * grep命令是你的好帮手
  * 首先,[配置](https://github.com/commaai/openpilot/tree/master/tools#setup-your-pc)你的电脑环境
  * 阅读文档并查看tools/和selfdrive/debug/中的工具
  * 提示:一旦你启动了回放和UI,先熟悉一下回放中的定位功能

开始使用
```bash
# 启动路线回放
cd tools/replay
./replay '0c7f0c7f0c7f0c7f|2021-10-13--13-00-00' --dcam --ecam

# 在另一个终端中启动UI
selfdrive/ui/ui
```
