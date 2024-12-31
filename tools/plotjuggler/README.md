# PlotJuggler插件

这是一个[PlotJuggler](https://github.com/facontidavide/PlotJuggler)插件,用于可视化openpilot日志。

## 安装

PlotJuggler已包含在openpilot的Ubuntu安装中。请参阅[openpilot维基](https://github.com/commaai/openpilot/wiki/Installing-openpilot#build-from-source)获取安装说明。

## 使用方法

### 离线模式

你可以通过以下方式加载日志:

1. 拖放多个文件(rlog.bz2和qlog.bz2)
2. 命令行: `plotjuggler --layout <布局文件> <日志文件>`

### 实时流模式

你可以从车辆实时流式传输数据:

```bash
# SSH转发ZMQ端口
ssh -L 1234:localhost:8019 <你的comma设备IP>

# 在本地运行plotjuggler
plotjuggler
```

然后点击: Streaming > Start > openpilot (ZMQ) > OK

### 演示

你也可以流式传输演示路线:

```bash
# Terminal 1 - 运行演示回放
cd tools/plotjuggler
./demo.py

# Terminal 2 - 运行plotjuggler
plotjuggler
```

然后点击: Streaming > Start > openpilot (ZMQ) > OK

## 创建自定义布局

1. 从左侧边栏拖动你想要的信号进行绘图
2. 组织图表布局
3. 保存布局: `File > Save Layout`

### 共享布局

布局保存为XML文件。你可以在[这里](layouts)找到默认布局。如果你想分享你的布局,欢迎创建PR!
