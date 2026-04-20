"""视频合成模块 - 将图片+音频合成为视频 (moviepy v2)"""

import logging
import os

from moviepy import AudioFileClip, ImageClip
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)


class VideoComposer:
    def __init__(self, config: dict):
        self.config = config
        self.fps = config["video"]["fps"]
        self.width, self.height = config["video"]["resolution"]
        self.codec = config["video"]["codec"]

    def compose(self, image_path: str, audio_path: str, output_path: str, title: str = "") -> str:
        """
        将一张图片和一段音频合成为视频。

        Args:
            image_path: 图片文件路径
            audio_path: 音频文件路径
            output_path: 输出视频路径
            title: 可选的章节标题

        Returns:
            str: 生成的视频文件路径
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # 加载音频获取时长
        audio = AudioFileClip(audio_path)
        duration = audio.duration

        # 加载并调整图片尺寸
        img = Image.open(image_path)
        img = self._resize_and_pad(img)
        img_array = np.array(img)

        # moviepy v2: 用关键字参数创建 ImageClip
        video_clip = ImageClip(img_array, duration=duration)
        video_clip = video_clip.with_audio(audio)

        # 写入视频文件
        video_clip.write_videofile(
            output_path,
            codec=self.codec,
            audio_codec="aac",
            fps=self.fps,
            logger=None,
        )

        # 清理资源
        video_clip.close()
        audio.close()

        logger.info(f"视频合成完成: {output_path} (时长: {duration:.1f}秒)")
        return output_path

    def _resize_and_pad(self, img: Image.Image) -> Image.Image:
        """调整图片尺寸，保持比例并填充黑边"""
        target_w, target_h = self.width, self.height

        ratio = min(target_w / img.width, target_h / img.height)
        new_w = int(img.width * ratio)
        new_h = int(img.height * ratio)

        img = img.resize((new_w, new_h), Image.LANCZOS)

        background = Image.new("RGB", (target_w, target_h), (0, 0, 0))
        offset_x = (target_w - new_w) // 2
        offset_y = (target_h - new_h) // 2
        background.paste(img, (offset_x, offset_y))

        return background
