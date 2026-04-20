# 参考声音样本目录

这里存放**你自己收集**的参考音色文件（`.wav` / `.mp3` / `.m4a` / `.flac`），作为 IndexTTS 声音克隆的参考。

## 目录约定

建议按**说话人 / 风格**组织：

```
voice_samples/
├── narrator/              # 叙事/朗读风格
│   ├── mo_chi.wav
│   └── example1.wav
├── male/                  # 男声
│   └── alex.wav
└── female/                # 女声
    └── xiaoxiao.wav
```

## 音色要求

| 要求 | 说明 |
|------|------|
| ⏱️ 长度 | **8-15 秒**（太短提取不准，太长反而混乱） |
| 🎙️ 单人 | 只有一个人说话，无对话 |
| 🔇 背景 | 干净，无音乐、回声、噪音 |
| 📢 来源 | **真人朗读**，避免用 AI 生成的音频当参考 |
| 🎭 风格 | 语气中性平稳，符合朗读场景 |
| 📻 音质 | 建议 44.1kHz/48kHz 以上，未经压缩 |

## 使用流程

### 1. 处理音频到标准格式

用项目自带工具把原始音频（手机录音、视频提取的声音等）处理成 IndexTTS 友好的格式：

```bash
conda activate selling
cd F:\Development\AIBook

# 处理并放入 IndexTTS characters 目录
python tools/prepare_voice.py voice_samples/narrator/raw.m4a mo_chi --start 3 --duration 12
```

这个命令会：
- 从 `voice_samples/narrator/raw.m4a` 截取第 3-15 秒共 12 秒
- 做响度归一化、去噪、重采样到 24kHz 单声道
- 输出到 `F:\Development\index-tts-fastapi\characters\mo_chi.wav`

### 2. 在生成书籍时使用

```bash
python main.py --book 阿甘正传.pdf --voice mo_chi --overwrite
```

`--voice` 对应 `characters/` 下的文件名（不带扩展名）。

## 推荐素材来源

- 🎙️ **自己录音**：手机录音 APP，安静环境，距嘴 15-20cm
- 📖 **有声书片段**：喜马拉雅、蜻蜓 FM 的专业朗读节目
- 🎞️ **纪录片旁白**：《舌尖上的中国》、BBC 中文纪录片
- 📺 **新闻播报**：央视新闻联播的某几句

⚠️ **避免用：** 影视对白（情绪太重）、综艺（有背景音）、AI 合成音频（套娃放大瑕疵）

## 版权提醒

此文件夹被 `.gitignore` 忽略（避免上传版权素材），你放的音频仅本地使用，不会推到 GitHub。
