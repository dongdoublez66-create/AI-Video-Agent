# AI Video Agent

Version: **1.0.0**

AI Video Agent 是一个 Windows 本地 AI 视频剪辑工具。用户填写自己的 OpenAI-compatible API Key，选择本地素材文件夹，输入想要的视频风格、关键帧偏好和重点内容，应用会自动生成剪辑脚本、时间线、字幕，并优先调用 DaVinci Resolve 导出成片；如果 DaVinci Resolve 不可用，则自动回退到 FFmpeg。

## 功能

- Windows 本地窗口界面
- 兼容 OpenAI 格式接口：DeepSeek、OpenAI、OpenRouter、硅基流动等
- 支持选择任意素材文件夹、BGM 文件夹和输出文件夹
- 自动生成剪辑脚本、`timeline.json`、SRT 字幕和运行报告
- DaVinci Resolve 优先：自动创建工程/时间线并导出 MP4
- FFmpeg 后备渲染：没有 DaVinci 时也能输出粗剪 MP4
- 默认中文界面和中文剪辑指令

## 环境要求

- Windows 10/11
- Python 3.10+
- pip
- FFmpeg，可加入系统 PATH，或自行创建 `tools/ffmpeg/bin/` 并放入 `ffmpeg.exe`
- 可选：DaVinci Resolve Studio，并启用本地脚本接口

Python 自带 `tkinter`，本项目 1.0.0 默认不依赖大型 GUI 框架。

## 安装

克隆仓库：

```powershell
git clone https://github.com/dongdoublez66-create/AI-Video-Agent.git
cd AI-Video-Agent
```

创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

升级 pip 并安装项目：

```powershell
python -m pip install --upgrade pip
python -m pip install -e .
```

如果你的电脑没有 FFmpeg，可以自行创建目录并把 `ffmpeg.exe` 放到：

```text
tools/ffmpeg/bin/ffmpeg.exe
```

或者安装到系统 PATH。

## 启动

源码方式：

```powershell
python -m ai_video_agent gui
```

安装后也可以运行：

```powershell
ai-video-agent-gui
```

## 使用方式

1. 打开应用。
2. 在“模型连接”里填写：
   - Base URL
   - API Key
   - 模型名称
3. 点击“验证 API”。
4. 选择素材文件夹。
5. 可选：选择 BGM 文件夹。
6. 选择输出文件夹。
7. 输入视频风格、关键帧补充、重点剪辑补充。
8. 点击底部“开始自动剪辑”。

DeepSeek 示例：

```text
Base URL: https://api.deepseek.com/v1
Model: deepseek-chat
```

## 输出内容

成片会保存到你在窗口中选择的输出文件夹。

项目内会保留过程产物：

```text
outputs/logs/       # 剪辑脚本和渲染日志
timelines/          # timeline.json
subtitles/          # SRT 字幕
workspace/runs/     # 每次运行的素材扫描、关键帧、报告
```

这些目录是运行时自动生成的本地数据，不作为 GitHub 仓库内容提交。

## DaVinci Resolve

如果 DaVinci Resolve 可用，Agent 会优先：

1. 连接 DaVinci Resolve 脚本接口
2. 创建或打开 `AI_Video_Agent` 工程
3. 创建新时间线
4. 导入素材和 BGM
5. 写入剪辑片段和 marker
6. 导出 MP4

如果连接失败，会自动使用 FFmpeg 渲染，不会中断整个剪辑流程。

## 命令行工具

检查环境：

```powershell
python -m ai_video_agent doctor
```

初始化目录：

```powershell
python -m ai_video_agent init
```

## 目录结构

```text
ai_video_agent/     # Agent 应用代码
README.md           # 使用说明
pyproject.toml      # pip 安装配置
.gitignore          # 忽略本地素材、输出、缓存和密钥
```

素材、BGM、输出视频、字幕、时间线、缓存等都由用户在应用里选择或由程序运行时生成，不需要放进仓库。

## 注意

- 不要把自己的 API Key 写进仓库。
- 原始素材只读，Agent 会把结果写到输出文件夹和 `workspace/`。
- 第一版主要面向自动粗剪，复杂转场、字幕样式、调色和音频混音可以在 DaVinci 里继续精修。
