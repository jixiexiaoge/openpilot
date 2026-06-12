# Navipilot / CP搭子 (CPlink) - 智能化 Comma3 导航数据桥梁

<div align="center">

[![GitHub Release](https://img.shields.io/github/v/release/jixiexiaoge/openpilot)](https://github.com/jixiexiaoge/openpilot/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Android%208.0%2B-green.svg)](https://developer.android.com)

**快速安装地址：** `binge.fit/cp`
**补充地址：** `navipilot/Carrotpilot`
**补充地址：** `i.carrotpilot.app/c3-wip`

</div>

---

## 🌿 分支说明

- **master**：主分支。
- **fishop**：现代、起亚等车型的国内特调版本，由飞扬开发，基于旧版本 CP。
- **Dragonpilot (DP)**：支持 C3 + C4，整体较稳定，但功能相对较少。
- **release**：IQ Pilot 最新分支，针对特斯拉、大众、本田等车型做了特调，支持方向盘最大力矩控制和大角度控制。
- **Carrotpilot (CP)**：CP 最新分支，供 C3 使用。
- **carrotZ6**：长安 Z6 专用，基于旧版本 CP。

---

## 📢 开源公告与分支选择

本项目现已公开并完全开源（100% 开源）。如果你对本项目感兴趣，可前往分支页面选择适合自己的版本：

- **分支入口**：https://github.com/jixiexiaoge/navipilot/branches

你可以直接下载代码后自行编译、生成并使用；也可以基于现有源码做剥离和二次开发，例如：

- 高德专用版本
- 腾讯专用版本
- 百度移植版本
- 谷歌地图版本及进一步完善版本

这些分支均为开源分支，支持按需修改与移植。项目已持续开发一年多，全国已有近 1000 位用户体验，其中 200+ 用户给予了赞助和支持，感谢大家的长期信任。

同时说明：

- 早期老版本软件的使用不受影响。
- 如有需求，可自行编译并使用新版本。
- 若有人将本项目源码打包收费售卖，请谨慎甄别，避免上当。

本软件当前已具备较强能力，包括多导航源桥接、NOO 导航分发、自动模式切换、模型切换、7000 端口 Web 控制等，并将持续完善。

---

## 📖 目录 (Table of Contents)

- [项目简介 (Introduction)](#项目简介)
- [核心能力 (Core Capabilities)](#-核心能力)
- [设备要求 (Requirements)](#️-设备要求)
- [功能对比 (Feature Comparison)](#-功能对比一览)
- [进阶专业特性 (Advanced Features)](#-进阶专业特性)
- [下载与安装 (Download & Install)](#-下载与安装)
- [分支说明 (Branch Guide)](#-分支说明)
- [开源公告与分支选择 (Open-Source Notice)](#-开源公告与分支选择)
- [使用指南 (User Guide)](#-使用指南)
- [常见问题 (FAQ)](#-常见问题)
- [技术规格 (Technical Specs)](#-技术规格)
- [支持项目 (Support)](#-支持项目)
- [English Documentation](#english-documentation)

---

## 项目简介

一款由 [JixieXiaoGe](https://github.com/jixiexiaoge) 开发的专为 Comma3 设备与 CarrotPilot 深度打造的 Android "导航数据桥接"应用。

**CP搭子 (CPlink)** 目前正在进行做减法开发，主动移除过去偏臃肿、维护成本高的功能模块，集中资源把真正高频、刚需、稳定性的核心能力继续打磨好。当前重点是把多导航源的数据稳定分发给 CarrotPilot，服务 NOO 场景，并持续完善端侧控制与无屏化体验。

### ✨ 核心优势

- 🎯 **减法聚焦**：移除冗余模块，集中打磨最常用、最稳定的核心链路。
- 🗺️ **多导航源支持**：支持高德车机版、腾讯导航、高德手机版导航、谷歌地图导航。
- 🔁 **NOO 数据分发**：将导航数据稳定分发给 CarrotPilot，支撑更完整的 NOO 使用体验。
- 🌐 **无屏化增强**：7000 端口 Web 功能持续增强，逐步支持 comma 设备脱离屏幕使用。
- 💪 **持续可用**：长期实际路测验证，后台运行稳定，迭代方向明确。

---

## 🚀 核心能力

- **多源导航分发**: 接入高德车机版、腾讯导航、高德手机版与谷歌地图的导航数据，并稳定分发给 CarrotPilot。
- **NOO 场景支持**: 聚焦导航桥接主链路，让路线、转向与导航状态更好服务于 NOO 场景。
- **自动实验模式切换**: 根据路况与驾驶状态自动切换模式，减少人工频繁介入。
- **模型选择切换器**: 支持常用模型快速切换，便于不同车辆与驾驶偏好下使用。
- **端侧增强功能**: 持续完善 LED 屏幕功能、自动超车功能与驾驶报告。
- **7000 Web 控制台**: Web 功能已经非常丰富，可承担大量原本依赖屏幕的操作，逐步实现 comma 设备无屏使用。

---

## 🛠️ 设备要求

- **移动端**: Android 8.0+ 手机，安装高德地图 APP 与 CP搭子。
- **设备端**: Comma3 硬件，已安装 CarrotPilot 软件。
- **网络**: 手机与设备必须处于同一本地 WiFi 网络环境下。

---

## 📊 功能对比一览

对比 carrotman（韩国原版）、CPlink（CP搭子）与 CarrotAmap 当前更贴近实际使用的能力：

| 功能 | carrotman (韩国原版) | **CPlink (CP搭子)** | CarrotAmap |
| :--- | :---: | :---: | :---: |
| **导航源支持** | TMAP / Waze | **高德车机 / 腾讯 / 高德手机版 / 谷歌地图** | 高德地图车机版 |
| **导航数据分发至 CarrotPilot** | ✅ | ✅ **当前核心能力** | 🟡 部分 |
| **自动实验模式切换** | ❌ | ✅ | ❌ |
| **模型选择切换器** | ❌ | ✅ | ❌ |
| **LED 屏幕功能** | ❌ | ✅ | ❌ |
| **自动超车功能** | ❌ | ✅ | ❌ |
| **驾驶报告** | ❌ | ✅ | ❌ |
| **7000 Web 无屏控制** | ❌ | ✅ **重点完善中** | ❌ |
| **后台运行稳定性** | ✅ | ✅ **极高** | 🟡 存在闪退 |

> *图例：✅ 支持｜🟡 部分/进行中｜❌ 不支持*

---

## 🌟 进阶专业特性

### 1. 多导航源分发引擎 (Multi-Source Navigation Bridge)
聚焦高德车机版、腾讯导航、高德手机版与谷歌地图四类主流导航源，统一解析并分发导航数据给 CarrotPilot，用于更稳定地支撑 NOO 场景。

### 2. 自动实验模式与模型切换 (Auto Experiment + Model Switcher)
围绕实际驾驶场景持续完善自动实验模式切换能力，并提供模型选择切换器，降低手动操作成本，提高不同车型与风格下的可用性。

### 3. 7000 Web 控制台与端侧功能 (Port 7000 Web Console)
7000 端口现已承载丰富的 Web 功能，可用于设备控制、状态查看与部分交互操作，方向上是让 comma 设备逐步摆脱对屏幕的依赖；同时继续完善 LED 屏幕、自动超车与驾驶报告等功能。

---

## 📥 下载与安装

### 方式一：Comma3 设备直接安装
在 Comma3 设备浏览器中访问：
```
binge.fit/cp
openpilot/Carrotpilot
i.carrotpilot.app/c3-wip
```

### 方式二：GitHub 下载
访问 [GitHub Releases](https://github.com/jixiexiaoge/openpilot/releases) 页面下载最新版本 APK 文件。

### 安装步骤

1. **手机端准备**
   - 确保 Android 版本 ≥ 8.0
   - 安装最新版本高德地图
   - 下载并安装 CP搭子 APK

2. **首次启动配置**
   - 打开 CP搭子应用
   - 授予必要权限（位置、网络）
   - 等待自动连接 Comma3 设备

3. **连接验证**
   - 确保手机与 Comma3 在同一 WiFi 网络
   - 应用显示"已连接"状态即可使用

4. **Web 控制台**
   - 在同一网络下可访问 7000 端口 Web 功能
   - 可进行更多设备控制与状态查看
   - 适合无屏或弱依赖屏幕的使用场景

---

## 📱 使用指南

### 快速开始

1. **启动导航**
   - 打开高德车机版、腾讯导航、高德手机版或谷歌地图，设置目的地并开始导航
   - 打开 CP搭子应用

2. **自动连接**
   - 应用会自动搜索并连接 Comma3 设备
   - 连接成功后，导航数据自动同步

3. **开始驾驶**
   - Comma3 自动接收并使用导航数据
   - 导航信息将分发给 CarrotPilot，用于更完整的 NOO 使用场景

### 主要功能操作

- **🧭 导航桥接**：接入多种导航源并分发给 CarrotPilot。
- **🧪 自动实验模式**：根据状态自动切换实验模式。
- **🔀 模型切换器**：按车型或偏好快速切换模型。
- **💡 扩展功能**：持续完善 LED 屏幕、自动超车与驾驶报告。
- **🌐 Web 控制台**：通过 7000 端口 Web 管理更多设备功能，逐步实现无屏使用。

### 详细功能说明

了解更多与完整功能清单，请参见：
- 📖 [CP搭子 - 应用功能详细说明](./app功能说明.md)

---

## ❓ 常见问题

### Q1: 应用显示"搜索设备中..."，一直连接不上？
**解决方案：**
- ✅ 确认 Comma3 设备已开机并运行 CarrotPilot
- ✅ 检查手机和 Comma3 是否在同一 WiFi 网络
- ✅ 确认防火墙未阻止端口 7000、7705 和 7706
- ✅ 尝试重启应用或重新连接 WiFi

### Q2: 为什么收不到高德地图的数据？
**解决方案：**
- ✅ 确保高德地图正在导航（必须开始导航才会发送数据）
- ✅ 使用最新版本高德地图
- ✅ 检查手机是否允许应用后台运行
- ✅ 授予应用所有必要权限

### Q3: 区间限速不显示？
**解决方案：**
- ✅ 确认导航路线中确实有区间测速路段
- ✅ 使用高德地图完整版（非简化版）
- ✅ 检查应用与 Comma3 的连接状态

### Q4: GPS 坐标显示为 0？
**解决方案：**
- ✅ 检查是否授予了位置权限
- ✅ 确认手机 GPS 功能已开启
- ✅ 在户外空旷地带测试（室内 GPS 信号弱）

### Q5: 应用在后台会自动停止？
**解决方案：**
- ✅ 授予应用后台运行权限
- ✅ 在手机设置中将应用加入白名单
- ✅ Android 10+ 需要授予后台位置权限
- ✅ 关闭电池优化功能

更多问题请查看详细文档或加入用户群咨询。

---

## 🔧 技术规格

### 系统要求

| 项目 | 要求 |
|------|------|
| **Android 版本** | 8.0 (API 26) 或更高 |
| **高德地图版本** | 支持标准广播接口的版本 |
| **Comma3 系统** | CarrotPilot 兼容系统 |
| **网络要求** | WiFi（手机与设备同一网络） |

### 数据传输规格

| 参数 | 规格 |
|------|------|
| **传输协议** | UDP（用户数据报协议） |
| **数据格式** | JSON / Web 控制接口 |
| **发送频率** | 依导航源与控制类型动态调整 |
| **数据包大小** | 依据导航与控制数据内容变化 |
| **监听端口** | 7000（Web 控制台）、7705（设备发现）、7706（数据传输） |

### 当前重点能力

- ✅ **导航数据桥接**：高德车机版、腾讯导航、高德手机版、谷歌地图
- ✅ **NOO 导航分发**：将导航信息稳定分发给 CarrotPilot
- ✅ **自动实验模式切换**：减少人工干预，提高连续使用体验
- ✅ **模型选择切换器**：快速切换适合当前车辆与风格的模型
- ✅ **7000 Web 控制台**：支持更多设备管理与无屏化操作
- ✅ **端侧增强能力**：LED 屏幕、自动超车、驾驶报告

---

## ☕ 支持项目

如果您觉得 CP搭子 对您有帮助，欢迎通过以下方式支持项目开发：

### 加入用户社群

添加微信管理员加入 CarrotPilot 爱好者群：
- 微信号：`carrotpilot-JX`
- 微信号：`wbk18820232680`

### 赞助支持

您的支持将帮助我们：
- 🚀 开发更多新功能
- 🐛 修复 Bug 和优化性能
- 📚 完善文档和教程
- 💬 提供更好的技术支持

<div align="center">

**微信赞助**

![微信赞助](/wechat.jpg "微信赞助与入群")

**PayPal 赞助**

![PayPal 赞助](/paypal.png "Donate via PayPal")

</div>

---

## 📄 版本信息

- **当前版本**：2.3
- **最后更新**：2026-02-25
- **开发者**：[JixieXiaoGe](https://github.com/jixiexiaoge)

---

## 📜 许可证

本项目采用开源许可证发布。使用前请仔细阅读相关条款。

---

## 🙏 致谢

感谢所有支持和使用 CP搭子 的用户，您的反馈和建议是我们不断改进的动力！

特别感谢：
- CarrotPilot 团队提供的优秀系统平台
- 高德地图提供的导航数据支持
- 所有赞助者和贡献者的支持

---

<div id="english-documentation"></div>

# 🌐 Navipilot / CPlink - Professional Comma3 Navigation Bridge

<div align="center">

[![GitHub Release](https://img.shields.io/github/v/release/jixiexiaoge/openpilot)](https://github.com/jixiexiaoge/openpilot/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Android%208.0%2B-green.svg)](https://developer.android.com)

**Quick Installation:** `binge.fit/cp`
**Alternate Address:** `openpilot/Carrotpilot`
**Alternate Address:** `i.carrotpilot.app/c3-wip`

</div>

---

## 🌿 Branch Guide

- **master**: Main branch.
- **fishop**: Domestic custom branch for Hyundai, Kia, and related models, developed by Feiyang and based on an older CP version.
- **Dragonpilot (DP)**: Supports both C3 and C4. It is relatively stable, but has fewer features.
- **release**: Latest IQ Pilot branch with model-specific tuning for Tesla, Volkswagen, Honda, and others. Supports maximum steering torque control and large-angle steering control.
- **Carrotpilot (CP)**: Latest CP branch intended for C3.
- **carrotZ6**: Dedicated branch for Changan Z6, based on an older CP version.

---

## 📢 Open-Source Notice and Branch Selection

This project is now public and fully open source (100% open source). If you are interested, choose the version that fits your needs from the branches page:

- **Branches page**: https://github.com/jixiexiaoge/navipilot/branches

You can download the code, build it yourself, and use it directly. You can also split and adapt the source for secondary development, such as:

- AMAP-only editions
- Tencent-only editions
- Baidu-ported editions
- Google Maps editions and further improvements

All these branches are open-source branches and can be modified or ported as needed. The project has been developed for more than one year, with nearly 1,000 users across China having tried it, and more than 200 users providing sponsorship and support. Thank you for the long-term support.

Please also note:

- Early legacy versions are not affected and can still be used.
- If needed, you can compile and use newer versions yourself.
- If someone repackages this open-source code and charges for it, verify carefully and avoid scams.

The software already provides strong capabilities, including multi-source navigation bridging, NOO data delivery, automatic mode switching, model switching, and port 7000 Web control, and it will continue to improve.

## 📋 Table of Contents

- [Introduction](#introduction)
- [Core Capabilities](#-core-capabilities)
- [System Requirements](#-system-requirements)
- [Feature Comparison](#-feature-comparison)
- [Advanced Features](#-advanced-professional-features)
- [Download & Install](#-download--installation)
- [Branch Guide](#-branch-guide)
- [Open-Source Notice](#-open-source-notice-and-branch-selection)
- [Quick Start Guide](#-quick-start-guide)
- [Frequently Asked Questions](#-frequently-asked-questions)
- [Technical Specifications](#-technical-specifications)
- [Support the Project](#-support-the-project)

---

## Introduction

A professional-grade Android "Navigation Data Bridge" application specifically crafted for Comma3 hardware and CarrotPilot software, developed by [JixieXiaoGe](https://github.com/jixiexiaoge).

**CPlink (CP搭子)** is currently being streamlined on purpose. Older, bulky modules are being removed so development can stay focused on the features that matter most in daily driving: stable navigation bridging, NOO-oriented data delivery, device-side controls, and a stronger screenless workflow.

### ✨ Key Advantages

- 🎯 **Focused by Subtraction**: Removes heavy legacy modules and concentrates on the features used most often.
- 🗺️ **Multi-Source Navigation**: Supports AMAP head-unit edition, Tencent Navigation, AMAP mobile, and Google Maps.
- 🔁 **NOO Data Delivery**: Reliably distributes navigation data to CarrotPilot for NOO-oriented workflows.
- 🌐 **Screenless Direction**: Port 7000 now exposes a rich Web console, making screenless comma usage increasingly practical.
- 💪 **Built for Daily Use**: Road-tested, stable in the background, and iterating in a clear direction.

---

## 🛡️ Core Capabilities

- **Multi-Source Navigation Bridging**: Ingests navigation data from AMAP head-unit edition, Tencent Navigation, AMAP mobile, and Google Maps, then distributes it to CarrotPilot.
- **NOO-Oriented Workflow**: Keeps the navigation bridge focused on the route and state data that matter most for NOO usage.
- **Automatic Experimental Mode Switching**: Switches driving mode automatically based on road and driving context.
- **Model Selection Switcher**: Quickly changes between supported models for different vehicles and driving preferences.
- **Device-Side Enhancements**: Ongoing work on LED screen features, auto overtaking, and driving reports.
- **Port 7000 Web Console**: Rich Web features now cover more device control and status flows, enabling screenless usage scenarios.

---

## 📊 System Requirements

### Hardware Requirements
- **Mobile Device**: Android 8.0+ smartphone with AMAP app installed
- **Comma3 Device**: Comma3 hardware with CarrotPilot software
- **Network**: Both devices must be on the same local WiFi network

### Software Requirements
- AMAP (AutoNavi) navigation app
- CPlink (CP搭子) Android application
- Location and network permissions granted

---

## 📊 Feature Comparison

Comparison of practical, currently emphasized capabilities between carrotman (Korean original), **CPlink (CP搭子)**, and CarrotAmap:

| Feature | carrotman (Korean) | **CPlink (CP搭子)** | CarrotAmap |
| :--- | :---: | :---: | :---: |
| **Navigation Sources** | TMAP / Waze | **AMAP head-unit / Tencent / AMAP mobile / Google Maps** | AMAP Car Version |
| **Navigation Delivery to CarrotPilot** | ✅ | ✅ **Core focus** | 🟡 Partial |
| **Automatic Experimental Switching** | ❌ | ✅ | ❌ |
| **Model Selection Switcher** | ❌ | ✅ | ❌ |
| **LED Screen Features** | ❌ | ✅ | ❌ |
| **Auto Overtake** | ❌ | ✅ | ❌ |
| **Driving Reports** | ❌ | ✅ | ❌ |
| **Port 7000 Screenless Web Control** | ❌ | ✅ **Actively expanding** | ❌ |
| **Background Stability** | ✅ | ✅ **Excellent** | 🟡 Occasional Crashes |

> *Legend: ✅ Supported | 🟡 Partial/In Progress | ❌ Not Supported*

---

## 🌟 Advanced Professional Features

### 1. Multi-Source Navigation Bridge
Focused support for AMAP head-unit edition, Tencent Navigation, AMAP mobile, and Google Maps. Navigation data is normalized and delivered to CarrotPilot for more stable NOO-oriented use.

### 2. Auto Experiment + Model Switcher
The app keeps improving automatic experimental mode switching and provides a practical model selector so users can adapt quickly to different cars and driving styles.

### 3. Port 7000 Web Console and Device Features
Port 7000 now hosts a feature-rich Web console for device control, status inspection, and interaction flows that used to depend on the screen. The direction is clear: make comma devices increasingly usable without a screen while continuing to improve LED features, auto overtaking, and driving reports.

---

## 📥 Download & Installation

### Method 1: Direct Installation on Comma3
Visit in Comma3 device browser:
```
binge.fit/cp
openpilot/Carrotpilot
i.carrotpilot.app/c3-wip
```

### Method 2: GitHub Download
Download the latest APK from [GitHub Releases](https://github.com/jixiexiaoge/openpilot/releases)

### Installation Steps

1. **Mobile Device Preparation**
   - Ensure Android version ≥ 8.0
   - Install latest version of AMAP
   - Download and install CPlink APK

2. **First Launch Configuration**
   - Open CPlink application
   - Grant necessary permissions (location, network)
   - Wait for automatic connection to Comma3 device

3. **Connection Verification**
   - Ensure phone and Comma3 are on same WiFi network
   - App displays "Connected" status when ready

4. **Web Console**
   - Access the port 7000 Web features on the same network
   - Use it for richer device control and status inspection
   - Useful for screenless or low-screen-dependency usage

---

## 🚀 Quick Start Guide

### Getting Started

1. **Start Navigation**
   - Open AMAP head-unit edition, Tencent Navigation, AMAP mobile, or Google Maps and start navigation
   - Launch CPlink application

2. **Automatic Connection**
   - App automatically searches for and connects to Comma3 device
   - Once connected, navigation data syncs automatically

3. **Start Driving**
   - Comma3 automatically receives and uses navigation data
   - The data is distributed to CarrotPilot for a more complete NOO-oriented workflow

### Main Features

- **🧭 Navigation Bridge**: Connect multiple navigation sources and distribute their data to CarrotPilot.
- **🧪 Auto Experimental Mode**: Switch modes automatically based on context.
- **🔀 Model Switcher**: Quickly choose the model that fits the current car or preference.
- **💡 Extended Features**: Ongoing work on LED screen features, auto overtaking, and driving reports.
- **🌐 Web Console**: Use port 7000 for richer device management and increasingly screenless workflows.

### Detailed Documentation

For complete feature list and detailed instructions:
- 📖 [CPlink - Detailed Feature Guide](./app功能说明.md) (Chinese)

---

## ❓ Frequently Asked Questions

### Q1: App shows "Searching for device..." but won't connect?
**Solution:**
- ✅ Confirm Comma3 device is powered on and running CarrotPilot
- ✅ Check that phone and Comma3 are on same WiFi network
- ✅ Ensure firewall is not blocking ports 7000, 7705, and 7706
- ✅ Try restarting app or reconnecting WiFi

### Q2: Not receiving AMAP data?
**Solution:**
- ✅ Ensure AMAP is actively navigating (data only sent during navigation)
- ✅ Use latest version of AMAP
- ✅ Check that phone allows background app operation
- ✅ Grant all necessary permissions

### Q3: Interval speed limit not showing?
**Solution:**
- ✅ Confirm route actually has interval speed cameras
- ✅ Use full version of AMAP (not lite version)
- ✅ Check connection status with Comma3

### Q4: GPS coordinates showing as 0?
**Solution:**
- ✅ Verify location permissions are granted
- ✅ Confirm phone GPS is enabled
- ✅ Test in outdoor open area (indoor GPS signal is weak)

### Q5: App stops in background?
**Solution:**
- ✅ Grant background operation permissions
- ✅ Add app to phone whitelist
- ✅ Android 10+ requires background location permission
- ✅ Disable battery optimization

For more questions, check detailed documentation or join user community.

---

## 🔧 Technical Specifications

### System Requirements

| Item | Requirement |
|------|-------------|
| **Android Version** | 8.0 (API 26) or higher |
| **AMAP Version** | Version supporting standard broadcast interface |
| **Comma3 System** | CarrotPilot compatible system |
| **Network** | WiFi (phone and device on same network) |

### Data Transmission Specs

| Parameter | Specification |
|-----------|---------------|
| **Protocol** | UDP (User Datagram Protocol) |
| **Data Format** | JSON / Web control endpoints |
| **Send Frequency** | Varies by navigation source and control flow |
| **Packet Size** | Depends on navigation and control payloads |
| **Ports** | 7000 (Web console), 7705 (device discovery), 7706 (data transmission) |

### Current Focus Areas

- ✅ **Navigation Bridging**: AMAP head-unit edition, Tencent Navigation, AMAP mobile, and Google Maps
- ✅ **NOO Data Delivery**: Reliable navigation distribution to CarrotPilot
- ✅ **Automatic Experimental Switching**: Less manual intervention during use
- ✅ **Model Selection Switcher**: Faster model changes for different cars and preferences
- ✅ **Port 7000 Web Console**: More device management and screenless interaction
- ✅ **Device-Side Enhancements**: LED screen features, auto overtaking, and driving reports

---

## ☕ Support the Project

If you find CPlink helpful, please support the project development:

### Join User Community

Add WeChat administrator to join CarrotPilot enthusiast group:
- WeChat: `carrotpilot-JX`
- WeChat: `wbk18820232680`

### Sponsor Support

Your support helps us:
- 🚀 Develop new features
- 🐛 Fix bugs and optimize performance
- 📚 Improve documentation and tutorials
- 💬 Provide better technical support

<div align="center">

**WeChat Sponsorship**

![WeChat Sponsorship](/wechat.jpg "WeChat Sponsorship & Community")

**PayPal Sponsorship**

![PayPal Sponsorship](/paypal.png "Donate via PayPal")

</div>

---

## 📄 Version Information

- **Current Version**: 2.3
- **Last Updated**: 2026-02-25
- **Developer**: [JixieXiaoGe](https://github.com/jixiexiaoge)

---

## 📜 License

This project is released under an open-source license. Please read the terms carefully before use.

---

## 🙏 Acknowledgments

Thanks to all users who support and use CPlink. Your feedback and suggestions are our driving force for continuous improvement!

Special thanks to:
- CarrotPilot team for the excellent system platform
- AMAP (AutoNavi) for navigation data support
- All sponsors and contributors for their support

---
