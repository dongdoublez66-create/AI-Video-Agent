# Timeline JSON 说明

`timeline.json` 是这个剪辑工作台的核心中间产物。Codex 会优先修改它，再调用渲染命令输出视频。

## 顶层字段

- `version`：时间线版本
- `brief`：原始剪辑需求
- `preset`：平台导出参数
- `background_music`：BGM 路径，可以为空
- `music_volume`：BGM 音量，通常 0.15-0.25
- `voiceover`：配音文件路径，第一版可为空
- `scenes`：镜头列表
- `subtitles`：字幕过程产物设置

## scene 字段

```json
{
  "id": "scene_01",
  "asset": "inputs/videos/a.mp4",
  "start": 0.0,
  "duration": 5.0,
  "transition": {
    "type": "fade",
    "duration": 0.35
  },
  "caption": "开场字幕",
  "notes": "剪辑意图"
}
```

## 平台预设

- `douyin`：1080x1920，适合抖音竖屏
- `moments`：1080x1920，适合朋友圈竖屏
- `lecture`：1920x1080，适合讲座横屏

