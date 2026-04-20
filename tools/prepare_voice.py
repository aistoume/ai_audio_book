"""参考音色处理工具 - 把任意音频/视频转换成 IndexTTS 参考音色格式

用法:
    python tools/prepare_voice.py 原始文件 [输出名]

示例:
    # 从 m4a 生成 alex.wav
    python tools/prepare_voice.py my_recording.m4a alex

    # 从 mp4 视频里截 5-15 秒
    python tools/prepare_voice.py speech.mp4 narrator --start 5 --duration 10

    # 从 mp3 处理（自动降噪 + 归一化）
    python tools/prepare_voice.py audiobook.mp3 host --start 30 --duration 12 --denoise
"""

import argparse
import os
import subprocess
import sys

# 输出到 index-tts-fastapi 的 characters/ 目录
CHARACTERS_DIR = r"F:\Development\index-tts-fastapi\characters"


def find_ffmpeg() -> str:
    """定位 ffmpeg 可执行文件"""
    import shutil
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise RuntimeError("找不到 ffmpeg，请 pip install imageio-ffmpeg")


def prepare(src, name, start=0, duration=12, denoise=False, fmt="wav"):
    ffmpeg = find_ffmpeg()
    os.makedirs(CHARACTERS_DIR, exist_ok=True)
    dst = os.path.join(CHARACTERS_DIR, f"{name}.{fmt}")

    # ffmpeg 滤镜链：
    # - loudnorm: 响度归一化（让音量合适）
    # - highpass=80: 去除 80Hz 以下低频噪音
    # - lowpass=12000: 去除超高频底噪
    af = "highpass=f=80,lowpass=f=12000,loudnorm=I=-16:TP=-2:LRA=7"
    if denoise:
        af = "afftdn=nf=-25," + af

    # 按格式选择编码器
    codec_args = []
    if fmt == "wav":
        codec_args = ["-c:a", "pcm_s16le"]
    elif fmt == "mp3":
        codec_args = ["-c:a", "libmp3lame", "-b:a", "192k"]  # 192kbps 保证质量
    elif fmt == "ogg":
        codec_args = ["-c:a", "libvorbis", "-q:a", "5"]

    cmd = [
        ffmpeg, "-y",
        "-ss", str(start),
        "-t", str(duration),
        "-i", src,
        "-af", af,
        "-ar", "24000",
        "-ac", "1",
        *codec_args,
        "-loglevel", "warning",
        dst,
    ]
    print(f"→ {' '.join(cmd)}")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 处理失败")

    size_kb = os.path.getsize(dst) / 1024
    print(f"\n✅ 完成: {dst}")
    print(f"   大小: {size_kb:.1f} KB, 时长: {duration} 秒, 24kHz 单声道")
    print(f"\n下一步: 在 config.yaml 里设置 voice: \"{name}\" 即可使用")


def main():
    parser = argparse.ArgumentParser(description="准备 IndexTTS 参考音色")
    parser.add_argument("src", help="源文件（wav/mp3/m4a/mp4等）")
    parser.add_argument("name", nargs="?", default="custom", help="输出音色名（默认 custom）")
    parser.add_argument("--start", type=float, default=0, help="起始时间（秒），从此处开始截取")
    parser.add_argument("--duration", type=float, default=12, help="截取时长（秒），推荐 10-15")
    parser.add_argument("--denoise", action="store_true", help="启用降噪（需 ffmpeg 5.0+）")
    parser.add_argument("--format", choices=["wav", "mp3", "ogg"], default="wav",
                        help="输出格式，默认 wav（推荐，无损）")
    args = parser.parse_args()

    if not os.path.isfile(args.src):
        print(f"错误：文件不存在: {args.src}")
        sys.exit(1)

    prepare(args.src, args.name, args.start, args.duration, args.denoise, args.format)


if __name__ == "__main__":
    main()
