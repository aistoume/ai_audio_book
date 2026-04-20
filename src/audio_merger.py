"""音频合并工具 - 将多个 WAV/MP3 片段按顺序合并为一个完整音频文件"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def merge_audio_files(
    input_files: list[str],
    output_path: str,
    gap_ms: int = 300,
) -> str:
    """
    按顺序合并音频文件为一个完整音频。

    优先策略：
      - 输入都是 WAV 且参数一致 → 用 Python wave 模块直接拼接（零依赖）
      - 否则 → 用 ffmpeg concat demuxer（moviepy 自带 imageio-ffmpeg）

    Args:
        input_files: 按顺序排列的音频文件路径
        output_path: 输出文件路径（根据扩展名决定格式）
        gap_ms: 片段之间插入的静默长度（毫秒），让听感更自然

    Returns:
        输出文件路径
    """
    if not input_files:
        raise ValueError("没有可合并的音频文件")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 检测输入格式
    exts = {Path(f).suffix.lower() for f in input_files}

    if exts == {".wav"} and output_path.lower().endswith(".wav"):
        # 纯 WAV 合并，使用 wave 模块
        try:
            return _merge_wavs_native(input_files, output_path, gap_ms)
        except Exception as e:
            logger.warning(f"wave 模块合并失败，改用 ffmpeg: {e}")

    # 其他情况用 ffmpeg
    return _merge_with_ffmpeg(input_files, output_path, gap_ms)


def _merge_wavs_native(input_files: list[str], output_path: str, gap_ms: int) -> str:
    """用 Python wave 模块直接拼接 WAV（要求所有输入采样率和格式一致）"""
    import wave

    with wave.open(input_files[0], "rb") as first:
        n_channels = first.getnchannels()
        sampwidth = first.getsampwidth()
        framerate = first.getframerate()

    gap_frames = int(framerate * gap_ms / 1000)
    silence = b"\x00" * (gap_frames * sampwidth * n_channels)

    with wave.open(output_path, "wb") as out:
        out.setnchannels(n_channels)
        out.setsampwidth(sampwidth)
        out.setframerate(framerate)

        for i, f in enumerate(input_files):
            with wave.open(f, "rb") as w:
                if (
                    w.getnchannels() != n_channels
                    or w.getsampwidth() != sampwidth
                    or w.getframerate() != framerate
                ):
                    raise RuntimeError(f"音频参数不一致: {f}")
                out.writeframes(w.readframes(w.getnframes()))
            if i < len(input_files) - 1 and gap_frames > 0:
                out.writeframes(silence)

    logger.info(f"WAV 合并完成: {output_path} ({len(input_files)} 段)")
    return output_path


def _merge_with_ffmpeg(input_files: list[str], output_path: str, gap_ms: int) -> str:
    """用 ffmpeg concat demuxer 合并任意格式的音频"""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "未找到 ffmpeg。请安装 ffmpeg 或通过 'pip install imageio-ffmpeg' 附带"
        )

    # ffmpeg concat 需要一个文件列表
    with tempfile.TemporaryDirectory() as tmp:
        list_file = os.path.join(tmp, "list.txt")

        # 准备静默段（如需要）
        silence_path = None
        if gap_ms > 0:
            silence_path = os.path.join(tmp, "silence.wav")
            subprocess.run(
                [
                    ffmpeg, "-y", "-f", "lavfi",
                    "-i", f"anullsrc=r=24000:cl=mono",
                    "-t", f"{gap_ms / 1000:.3f}",
                    "-loglevel", "error",
                    silence_path,
                ],
                check=True,
            )

        with open(list_file, "w", encoding="utf-8") as f:
            for i, af in enumerate(input_files):
                abs_path = os.path.abspath(af).replace("\\", "/")
                f.write(f"file '{abs_path}'\n")
                if silence_path and i < len(input_files) - 1:
                    f.write(f"file '{silence_path.replace(chr(92), '/')}'\n")

        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c:a", "libmp3lame" if output_path.lower().endswith(".mp3") else "pcm_s16le",
            "-loglevel", "error",
            output_path,
        ]
        subprocess.run(cmd, check=True)

    logger.info(f"ffmpeg 合并完成: {output_path} ({len(input_files)} 段)")
    return output_path


def _find_ffmpeg() -> str | None:
    """定位 ffmpeg 可执行文件。优先使用 imageio-ffmpeg 自带的"""
    # 1. 系统 PATH
    exe = shutil.which("ffmpeg")
    if exe:
        return exe

    # 2. imageio-ffmpeg 自带
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None
