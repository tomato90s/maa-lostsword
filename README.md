<!-- markdownlint-disable MD033 MD041 -->
<p align="center">
  <img alt="LOGO" src="https://cdn.jsdelivr.net/gh/MaaAssistantArknights/design@main/logo/maa-logo_512x512.png" width="256" height="256" />
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
| 公会 | 🚧 开发中 | 尚未支持 |
| 迷宫 | 🚧 开发中 | 尚未支持 |
| 星辰轮回 | 🚧 开发中 | 尚未支持 |

## 使用方法

### 1. 下载 Release

从 [Releases](https://github.com/andy90s/maa-lostsword/releases) 页面下载对应平台的安装包。

支持平台：
- Windows (x64 / ARM64)
- macOS (x64 / ARM64)
- Linux (x64 / ARM64)
- Android (x64 / ARM64)

### 2. 运行

解压后运行对应的可执行文件：

- **Windows**: `MaaXXX.exe`
- **macOS**: `MaaXXX.app`（首次运行可能需要手动签名）
- **Linux**: `MaaXXX`
- **Android**: 通过 MAA 安卓端加载

### 3. 连接设备

支持 ADB 连接模拟器或物理设备。推荐使用 BlueStacks、MuMu 等安卓模拟器运行游戏。

## 环境要求

- [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 运行环境
- ADB 调试连接（模拟器或真机）
- 游戏分辨率：1280x720（推荐）

## 开发说明

本项目使用 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 作为底层自动化框架，通过图像识别（OCR + 模板匹配）实现游戏操作的自动化。

Pipeline 配置文件位于 `assets/resource/pipeline/`，使用 JSON 格式定义识别节点和操作逻辑。

更多开发文档请参考 [MaaFramework 文档](https://github.com/MaaXYZ/MaaFramework/tree/main/docs)。

## 鸣谢

本项目由 **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 强力驱动！
