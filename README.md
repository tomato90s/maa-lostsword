<!-- markdownlint-disable MD033 MD041 -->
<p align="center">
  <img alt="LOGO" src="public/logo.webp" width="256" height="256" />
</p>

<div align="center">

# MAA-LostSword

基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 的 Lost Sword 自动化脚本

</div>

## 功能清单

| 功能 | 状态 | 说明 |
|------|------|------|
| 竞技场 | ✅ 可用 | 自动完成竞技场免费次数挑战，次数用尽后自动返回首页 |
| 副本扫荡 | ✅ 可用 | 自动扫荡黄金猎犬、经验书、属性石副本 |
| 巨石阵 | ✅ 可用 | 自动完成巨石阵副本挑战 |
| 宝藏探索 | ✅ 可用 | 自动完成首页宝藏探索领取 |
| 公会签到 | ✅ 可用 | 自动完成公会签到和投资 |
| 免费每日一抽 | ✅ 可用 | 自动完成每日免费召唤 |
| 每日商店购买 | 🚧 开发中 | 自动完成每日商店免费礼包和代币兑换（识别参数待补充） |
| 领取任务奖励 | ✅ 可用 | 自动领取每日/每周/史诗任务奖励 |
| 个人突袭 | ✅ 可用 | 自动完成个人突袭领主扫荡 |

## 使用方法

### 1. 下载 Release

从 [Releases](https://github.com/tomato90s/maa-lostsword/releases) 页面下载对应平台的安装包。

支持平台：
- Windows (x64 / ARM64)
- macOS (x64 / ARM64)

### 2. 自动更新

启动时会自动检查并下载资源更新，无需手动重新下载完整安装包。

- **更新范围**：`agent/`（Python 脚本）、`resource/`（任务配置）、`interface.json`
- **更新源**：自动尝试 GitHub 直连及多个镜像加速节点（`gh-proxy.com` 等）
- **下载反馈**：日志区域会显示实时进度、下载速度和文件大小

如果自动更新失败，仍可手动从 Releases 页面下载完整包覆盖。

### 3. 运行

解压后运行对应的可执行文件：

- **Windows**: `MaaLostSword.exe`
- **macOS**: `MaaLostSword.app`（首次运行可能需要手动签名）

### 4. 连接设备

支持 ADB 连接模拟器或物理设备。推荐使用 BlueStacks、MuMu 等安卓模拟器运行游戏。

### 5. 启动任务

- **模拟器自带加速**：可自动打开游戏进行任务
- **使用第三方加速器**：需手动打开并登录游戏，在游戏大厅启动任务

## 环境要求

- [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 运行环境
- **安卓模拟器**：推荐使用 BlueStacks、MuMu 等模拟器运行游戏（暂不支持 iOS 设备）
- **游戏语言**：简体中文（OCR 文字识别依赖中文界面）
- ADB 调试连接
- 游戏分辨率：1920x1080（推荐）/ 1280x720

## 开发说明

本项目使用 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 作为底层自动化框架，通过图像识别（OCR + 模板匹配）实现游戏操作的自动化。

Pipeline 配置文件位于 `assets/resource/pipeline/`，使用 JSON 格式定义识别节点和操作逻辑。

更多开发文档请参考 [MaaFramework 文档](https://github.com/MaaXYZ/MaaFramework/tree/main/docs)。

## 联系方式

- QQ 群：**1020907837**

## 鸣谢

本项目由 **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 强力驱动！
