# 如何贡献代码

我们的软件是开源的,这样你就可以自己解决问题而不需要依赖他人。如果你解决了某个问题并愿意分享,可以将代码贡献给社区供大家使用。详情请查看我们关于[外部化的博客文章](https://blog.comma.ai/a-2020-theme-externalization/)。

开发工作通过 [Discord](https://discord.comma.ai) 和 GitHub 进行协调。

### 入门指南

* 按照[开发环境设置指南](../tools/)配置环境
* 阅读[开发工作流程](WORKFLOW.md)
* 加入我们的 [Discord](https://discord.comma.ai)
* 文档请参考 https://docs.comma.ai 和 https://blog.comma.ai

## 我们需要什么样的贡献?

**openpilot的优先级按顺序是:[安全性](SAFETY.md)、稳定性、质量和功能。**
openpilot是comma实现*在提供可交付中间产品的同时解决自动驾驶汽车问题*这一使命的一部分,所有开发都是朝着这个目标进行的。

### 什么样的代码会被合并?

PR被合并的可能性取决于它对项目的价值以及我们合并它所需的工作量。
如果一个PR只提供*一些*价值但需要大量时间来合并,它将被关闭。
简单且经过充分测试的bug修复最容易被合并,而新功能最难被合并。

以下都是优秀PR的例子:
* typo fix: https://github.com/commaai/openpilot/pull/30678
* removing unused code: https://github.com/commaai/openpilot/pull/30573
* simple car model port: https://github.com/commaai/openpilot/pull/30245
* car brand port: https://github.com/commaai/openpilot/pull/23331

### 什么样的代码不会被合并?

* **样式修改**: 代码是艺术,如何让它变得优美取决于作者
* **超过500行的PR**: 需要清理代码,拆分成更小的PR,或者两者都做
* **没有明确目标的PR**: 每个PR必须有单一且明确的目标
* **UI设计**: 我们目前还没有一个好的UI审查流程
* **新功能**: 我们认为openpilot的功能已经基本完善,剩下的主要是改进和修复bug。因此,大多数功能性PR会被直接关闭。不过开源的好处是,分支可以提供上游openpilot没有的功能。
* **预期价值为负**: 这类PR虽然有改进,但风险或验证成本超过了改进带来的收益。可以通过先合并一个失败的测试来降低风险。

### 第一次贡献

[项目/openpilot悬赏任务](https://github.com/orgs/commaai/projects/26/views/1?pane=info)是最好的入门方式,详细说明了处理悬赏任务时的要求。
有很多悬赏任务不需要comma 3/3X设备或车辆就能完成。

## Pull Request(拉取请求)

Pull Request应该提交到master分支。

一个好的Pull Request应该包含以下所有内容:
* 明确说明目的
* 每一行修改都直接服务于所述目的
* 验证说明,即你如何测试你的PR
* 合理性证明
  * 如果你优化了某些内容,提供基准测试结果证明确实更好
  * 如果你改进了车辆调教,提供前后对比图
* 通过CI测试

## 无需编码的贡献方式

* 在GitHub issues中报告bug
* 在Discord的`#driving-feedback`频道反馈驾驶问题
* 考虑选择上传驾驶员摄像头数据以改进驾驶员监控模型
* 定期将设备连接到Wi-Fi,这样我们可以获取数据来训练更好的驾驶模型
* 运行`nightly`分支并报告问题。这个分支类似于`master`,但构建方式与正式发布版本相同
* 为[comma10k数据集](https://github.com/commaai/comma10k)标注图像
