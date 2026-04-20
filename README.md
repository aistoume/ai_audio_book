# AIBook - 书籍转有声书系统

把 PDF / TXT 书籍自动朗读生成**一个完整的 MP3/WAV 音频文件**。完全本地 TTS，逐字原文朗读，不做任何总结或改写。

## 流程概览

```
books/ (PDF/TXT)  →  提取原文  →  按标点智能分块  →  IndexTTS 逐块合成  →  合并为单个 MP3
                                                                              ↓
                                                            output/{书名}/audiobook.mp3
```

## TTS 引擎对比

本项目支持四种 TTS 引擎，各有侧重：

| TTS | 自然度 | 特长 | 适用场景 |
|-----|-------|------|---------|
| **IndexTTS** | ⭐⭐⭐⭐⭐ | 长文本朗读、韵律自然 | 有声书首选（通用推荐） |
| **GPT-SoVITS** | ⭐⭐⭐⭐⭐ | 零样本克隆，需同时提供参考音频+对应文字 | 想**高精度复刻特定人声**（要求参考音频 3-10 秒） |
| CosyVoice (SFT) | ⭐⭐⭐ | 多语言、多预设说话人 | 通用场景、稳定可用 |
| edge-tts | ⭐⭐ | 无需本地部署 | 无 GPU / 应急兜底 |

**选择建议：**
- 📖 朗读普通书籍 → `indextts`
- 🎭 想让某个具体人（比如自己）念书 → `gpt_sovits`（需提供参考音频+对应文字）
- 🌐 多语言混合 → `cosyvoice`
- 💻 无 GPU → `edge_tts`

## 项目结构

```
F:\Development\AIBook\
├── config.yaml                     # 配置（TTS 引擎、音色、语速等）
├── requirements.txt                # Python 依赖
├── main.py                         # 主入口
├── README.md                       # 本文档
├── books/                          # 📥 书籍输入（PDF/TXT 或子文件夹）
├── output/                         # 📤 输出（每本书一个文件夹）
│   └── {书名}/
│       ├── chunks.json             # 分块后的文本缓存
│       ├── progress.json           # 断点续传进度
│       ├── audio_chunks/*.wav      # 每块的 TTS 音频（用于断点续传）
│       └── audiobook.mp3           # ✅ 最终合并后的完整有声书文件
├── voice_samples/                  # 🎙️ 本地参考音色素材库（不上传到 git）
│   └── README.md                   # 使用说明
├── tools/
│   └── prepare_voice.py            # 参考音色预处理工具（截取/降噪/标准化）
└── src/
    ├── extractor.py                # 提取 PDF/TXT（支持子文件夹多卷合并）
    ├── text_splitter.py            # 按句号/逗号智能分块
    ├── tts_engine.py               # IndexTTS / CosyVoice / edge-tts 统一封装
    └── audio_merger.py             # 合并多块音频为一个文件
```

## 安装 & 启动

### 1️⃣ 安装 Python 依赖

```bash
conda activate selling    # 或你的主工作环境
cd F:\Development\AIBook
pip install -r requirements.txt
```

### 2️⃣ 安装并启动 IndexTTS 服务

**a. 克隆并安装**（新建独立 conda 环境）：

```bash
conda create -n indextts python=3.10 -y
conda activate indextts

# 主仓库
git clone https://github.com/index-tts/index-tts.git
cd index-tts
pip install -e .

# FastAPI 服务封装
git clone https://github.com/csllpr/index-tts-fastapi.git
cd index-tts-fastapi
pip install -r requirements.txt
```

**b. 下载模型**：

```bash
huggingface-cli download IndexTeam/Index-TTS \
  bigvgan_discriminator.pth bigvgan_generator.pth \
  bpe.model dvae.pth gpt.pth unigram_12000.vocab \
  --local-dir checkpoints
```

**c. 放一个参考音色文件**到 `characters/` 目录（5-10秒干净人声的 wav）：
```
characters/
  └── alex.wav     # 想让 TTS 模仿的声音样本
```

**d. 启动服务**：

GPU 模式（默认，需要 NVIDIA GPU + CUDA）：
```bash
python run.py --host 127.0.0.1 --port 8000
```

**CPU 模式**（无 GPU 的电脑使用）：
```bash
python run.py --host 127.0.0.1 --port 8000 --device cpu --no-fp16
```

也可以通过环境变量设置：
```bash
# Windows cmd
set TTS_DEVICE=cpu
set TTS_FP16=0
python run.py --host 127.0.0.1 --port 8000

# Windows PowerShell
$env:TTS_DEVICE="cpu"
$env:TTS_FP16="0"
python run.py --host 127.0.0.1 --port 8000

# Linux/Mac
TTS_DEVICE=cpu TTS_FP16=0 python run.py --host 127.0.0.1 --port 8000
```

> ⚠️ **CPU 模式性能提示：**
> - 每段生成约需 1-3 分钟（GPU 只需 5-10 秒）
> - 一本 5 万字书约 270 段 → 全量生成可能需要 **4-10 小时**
> - 建议在 `config.yaml` 把 `indextts.timeout` 调到 `1800`（30 分钟）避免超时
> - CPU 模式无法使用 FP16，质量与 GPU 模式基本一致

### 3.5️⃣（可选）启动 GPT-SoVITS 服务

如果你想用 **GPT-SoVITS** 做声音克隆（零样本，3-10 秒参考音频即可）：

#### a. 安装依赖

```bash
conda create -n gptsovits python=3.10 -y
conda activate gptsovits
git clone https://github.com/RVC-Boss/GPT-SoVITS.git
cd GPT-SoVITS
```

**Windows 特殊处理**（原版 requirements 里有几个包无法在 Windows 编译）：

```bash
# 1) 预编译版日语发音库（替代需要 CMake 的 pyopenjtalk）
pip install pyopenjtalk-prebuilt
```

编辑 `requirements.txt`，替换/注释三个包：
```
# pyopenjtalk>=0.4.1       ← 注释掉（已装 prebuilt 版）
# jieba_fast               ← 注释掉
jieba                       ← 保留
# opencc                   ← 注释掉
opencc-python-reimplemented ← 新增
```

然后：
```bash
pip install -r requirements.txt
```

#### b. 打补丁（Windows 兼容）

GPT-SoVITS 代码里硬编码了 `jieba_fast`，需要改成自动降级：

- `GPT_SoVITS/text/chinese.py` 和 `chinese2.py`：把 `import jieba_fast` 包进 try/except，降级到 `jieba`
- `GPT_SoVITS/text/tone_sandhi.py` 同理
- `GPT_SoVITS/TTS_infer_pack/TTS.py` 的 `_get_ref_spec()`：加 `soundfile` fallback（避免 Windows 上 torchcodec 问题）

（具体补丁见本仓库 commit 历史）

#### c. 下载模型

```bash
cd F:\Development\GPT-SoVITS
pip install -U huggingface_hub

# 基础 bert/hubert（约 2GB）
huggingface-cli download lj1995/GPT-SoVITS --include "chinese-hubert-base/*" "chinese-roberta-wwm-ext-large/*" --local-dir GPT_SoVITS/pretrained_models

# v2 预训练权重（约 400MB）
huggingface-cli download lj1995/GPT-SoVITS --include "gsv-v2final-pretrained/*" --local-dir GPT_SoVITS/pretrained_models

# G2PW 中文发音模型（约 1GB）
cd GPT_SoVITS/text
curl -L -o G2PWModel.zip https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/G2PWModel.zip
tar -xf G2PWModel.zip
cd ../..

# 创建 fast_langdetect 缓存目录
mkdir GPT_SoVITS\pretrained_models\fast_langdetect

# 下载 NLTK 数据（否则报 averaged_perceptron_tagger_eng 缺失）
python -c "import nltk; nltk.download('averaged_perceptron_tagger_eng'); nltk.download('cmudict'); nltk.download('punkt_tab')"
```

#### d. 设置 GPU 推理

编辑 `GPT_SoVITS/configs/tts_infer.yaml` 把 `custom:` 段改成：
```yaml
custom:
  device: cuda          # CPU 用户保持 cpu
  is_half: true         # CPU 用户设为 false
  # 其他字段保持默认
```

#### e. 启动 API 服务

```bash
python api_v2.py -a 127.0.0.1 -p 9880
```

#### f. 配置 AIBook

编辑 `F:\Development\AIBook\config.yaml`：
```yaml
tts:
  engine: "gpt_sovits"
  gpt_sovits:
    api_url: "http://127.0.0.1:9880"
    voice: "my_voice"                          # voice_samples/下的 wav 文件名
    prompt_text: "参考音频里的实际说话内容"     # ⚠️ 必须字字对应
    prompt_lang: "zh"
    text_lang: "zh"
    speed_factor: 1.0
```

#### g. 运行

```bash
python main.py --book 阿甘正传.pdf --engine gpt_sovits --overwrite
```

> ⚠️ **GPT-SoVITS 关键注意事项：**
> 1. **参考音频必须 3-10 秒**（超出范围会报错，用 `tools/prepare_voice.py --duration 8` 裁剪）
> 2. **`prompt_text` 必须是参考音频的真实说话内容**（字字对应）—— 不匹配会生成噪音不是人声
> 3. **建议自己录音**：清晰朗读 5-8 秒一句话，这样你 100% 知道 prompt_text 该填什么

### 3️⃣ 运行 AIBook

> ⚠️ IndexTTS 跑在 `indextts` 环境（端口 8000），AIBook 跑在 `selling` 环境，两个终端分开。

新开终端：
```bash
conda activate selling
cd F:\Development\AIBook

# 处理单本
python main.py --book 阿甘正传.pdf

# 批量处理（txt 列表，每行一个书名）
python main.py --list batch.txt

# 处理 books/ 下所有书
python main.py --all

# 强制覆盖已有输出
python main.py --all --overwrite

# 跳过已生成的
python main.py --all --skip-existing
```

完成后，在 `output/{书名}/audiobook.mp3` 找到完整有声书。

### 🎙️ 临时覆盖 TTS 参数（不用改 config.yaml）

支持三个 CLI 参数，只对本次运行生效：

| 参数 | 说明 | 示例值 |
|------|------|--------|
| `--voice` | 参考音色名（对应 `characters/{name}.wav/mp3`，不带扩展名） | `example1` / `alex` / `mo_chi` |
| `--speed` | 语速，1.0 正常，< 1 慢，> 1 快 | `0.9` / `1.0` / `1.1` |
| `--engine` | TTS 引擎 | `indextts` / `cosyvoice` / `edge_tts` |

```bash
# 临时换音色
python main.py --book 阿甘正传.pdf --voice example1 --overwrite

# 音色 + 语速
python main.py --book 阿甘正传.pdf --voice alex --speed 0.9 --overwrite

# 临时切换到 CosyVoice（如 IndexTTS 服务挂了）
python main.py --book 阿甘正传.pdf --engine cosyvoice --voice 中文女 --overwrite

# 多音色快速对比（同一本书，不同音色）
python main.py --book test.txt --voice alex --overwrite
python main.py --book test.txt --voice mo_chi --overwrite
python main.py --book test.txt --voice example1 --overwrite
```

> 💡 未指定时使用 `config.yaml` 里的默认值。CLI 参数不会写回配置文件。

## 书籍输入格式

`books/` 目录支持两种形式：

**1. 单文件**：
```
books/
├── 阿甘正传.pdf
└── 三体.txt
```

**2. 多卷子文件夹**（合并为一个有声书）：
```
books/
└── 三体全集/
    ├── 第一部.txt
    ├── 第二部.txt
    └── 第三部.txt
```

子文件夹会按**文件名中的编号**自动排序合并：
- 阿拉伯数字：`第1卷`、`vol_02`
- 中文数字：`第一卷`、`卷二`、`第十章`
- 大写数字：`壹`、`贰`、`叁`

## 配置说明 (config.yaml)

```yaml
tts:
  engine: "indextts"           # indextts | cosyvoice | edge_tts

  indextts:
    api_url: "http://127.0.0.1:8000"
    voice: "alex"              # 对应 IndexTTS characters/{voice}.wav
    response_format: "wav"
    sample_rate: 24000
    speed: 1.0

audio:
  output_format: "mp3"         # 最终合并格式
  gap_ms: 300                  # 片段间静默（毫秒）

processing:
  max_chars_per_segment: 300   # 每段最大字符数
  min_chars_per_segment: 50
```

## 断点续传

每本书有独立的 `progress.json`，重跑相同命令会跳过已生成的分段。

- `--resume`（默认）：保留已有分段，继续未完成部分
- `--overwrite`：清空并重做整本
- `--skip-existing`：完全跳过已有完整音频的书

**强制重做某一段**：删除 `output/{书名}/audio_chunks/` 下对应的 `.wav` 文件即可，下次跑会自动补齐。

## 常见问题

**Q: IndexTTS 服务起不来**
检查模型文件是否齐全（`checkpoints/` 下6个文件），以及是否有至少1个 wav 放在 `characters/` 下。

**Q: 想换音色**
在 IndexTTS 的 `characters/` 目录加一个新的 wav（5-10秒干净人声），然后改 `config.yaml` 的 `voice` 字段为文件名（不带扩展名）。

**Q: 合并音频时报 ffmpeg not found**
`imageio-ffmpeg` 包应该会自动提供，检查是否装上：`pip install imageio-ffmpeg`。

**Q: 没有 GPU 能跑 IndexTTS 吗？**
可以但非常慢。建议使用至少 6GB 显存的 NVIDIA GPU。

**Q: 一本书生成要多久？**
5万字左右的书籍约 15-30 分钟（看 GPU 性能），最终 MP3 约 100-150MB。
