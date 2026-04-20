"""TTS语音合成模块 - CosyVoice2本地服务 + edge-tts备用"""

import asyncio
import io
import logging
import os
import struct
import wave
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

VOICE_EXTS = (".wav", ".mp3", ".m4a", ".flac", ".ogg")


def resolve_voice(voice: str, voice_samples_dir: str = "voice_samples") -> str:
    """
    解析 voice 参数为可用的音色标识（绝对路径或名字）。

    优先级：
      1. 如果是已存在的绝对/相对文件路径 → 返回绝对路径（传给服务端直接用）
      2. 在 voice_samples/ 下递归查找匹配的文件名 → 返回绝对路径
      3. 否则原样返回（让服务端在 characters/ 下查找）
    """
    # 1. 已经是文件路径
    p = Path(voice)
    if p.is_file():
        return str(p.resolve())

    # 2. 在 voice_samples/ 下递归查找
    samples_root = Path(voice_samples_dir)
    if samples_root.exists():
        base_name = p.stem if p.suffix else voice
        for f in samples_root.rglob("*"):
            if f.is_file() and f.suffix.lower() in VOICE_EXTS:
                if f.stem == base_name:
                    logger.info(f"在 voice_samples/ 中找到音色: {f}")
                    return str(f.resolve())

    # 3. 原样返回，让服务端在 characters/ 下找
    return voice


class TTSEngine:
    def __init__(self, config: dict):
        self.config = config
        self.engine = config["tts"]["engine"]

    def synthesize(self, text: str, output_path: str) -> str:
        """将文本合成为语音文件"""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        if self.engine == "cosyvoice":
            return self._cosyvoice_tts(text, output_path)
        elif self.engine == "indextts":
            return self._indextts(text, output_path)
        elif self.engine == "gpt_sovits":
            return self._gpt_sovits(text, output_path)
        elif self.engine == "edge_tts":
            return self._edge_tts(text, output_path)
        else:
            raise ValueError(f"不支持的TTS引擎: {self.engine}")

    def _gpt_sovits(self, text: str, output_path: str) -> str:
        """
        调用 GPT-SoVITS v2 FastAPI 服务（api_v2.py）。
        端点: POST /tts
        返回: 音频字节（wav/ogg/aac/raw）

        GPT-SoVITS 与 IndexTTS 不同：需要 prompt_text（参考音频对应的文字）+ ref_audio_path。
        """
        cfg = self.config["tts"]["gpt_sovits"]
        api_url = cfg["api_url"]

        # 解析参考音频路径（同 IndexTTS 的逻辑，但 GPT-SoVITS 需要服务端能访问的绝对路径）
        voice = cfg.get("voice", "")
        voice_samples_dir = self.config.get("processing", {}).get(
            "voice_samples_dir", "voice_samples"
        )
        ref_audio_path = resolve_voice(voice, voice_samples_dir) if voice else cfg.get("ref_audio_path", "")
        if not ref_audio_path or not os.path.isabs(ref_audio_path):
            # 转为绝对路径
            ref_audio_path = os.path.abspath(ref_audio_path)

        media_type = cfg.get("media_type", "wav")
        timeout = cfg.get("timeout", 300)

        payload = {
            # 必需参数
            "text": text,
            "text_lang": cfg.get("text_lang", "zh"),         # zh/en/ja/ko 等
            "ref_audio_path": ref_audio_path,
            "prompt_lang": cfg.get("prompt_lang", "zh"),     # 参考音频的语言
            # 推荐参数
            "prompt_text": cfg.get("prompt_text", ""),       # 参考音频对应的文字
            "text_split_method": cfg.get("text_split_method", "cut5"),
            "speed_factor": cfg.get("speed_factor", 1.0),
            "media_type": media_type,
            "streaming_mode": False,
            # 采样参数（影响质量）
            "top_k": cfg.get("top_k", 15),
            "top_p": cfg.get("top_p", 1.0),
            "temperature": cfg.get("temperature", 1.0),
            "repetition_penalty": cfg.get("repetition_penalty", 1.35),
            "batch_size": cfg.get("batch_size", 1),
            "parallel_infer": cfg.get("parallel_infer", True),
        }

        try:
            resp = requests.post(
                f"{api_url}/tts",
                json=payload,
                timeout=timeout,
            )

            if resp.status_code != 200:
                # GPT-SoVITS 出错时返回 JSON
                try:
                    err = resp.json()
                except ValueError:
                    err = resp.text
                raise RuntimeError(f"GPT-SoVITS HTTP {resp.status_code}: {err}")

            # 修正输出路径扩展名
            if not output_path.lower().endswith(f".{media_type}"):
                output_path = os.path.splitext(output_path)[0] + f".{media_type}"

            with open(output_path, "wb") as f:
                f.write(resp.content)

            logger.info(f"GPT-SoVITS 完成: {output_path}")
            return output_path

        except requests.RequestException as e:
            logger.error(f"GPT-SoVITS 调用失败: {e}")
            raise

    def _indextts(self, text: str, output_path: str) -> str:
        """
        调用 IndexTTS FastAPI 服务（OpenAI兼容接口）。
        端点: POST /v1/audio/speech
        返回: 音频字节（mp3/wav）
        """
        cfg = self.config["tts"]["indextts"]
        api_url = cfg["api_url"]
        token = cfg.get("token", "test_token")
        voice = cfg.get("voice", "alex")
        # 自动解析：优先在项目的 voice_samples/ 下查找，传绝对路径给服务端
        voice_samples_dir = self.config.get("processing", {}).get(
            "voice_samples_dir", "voice_samples"
        )
        voice = resolve_voice(voice, voice_samples_dir)
        fmt = cfg.get("response_format", "wav")
        sample_rate = cfg.get("sample_rate", 24000)
        speed = cfg.get("speed", 1.0)
        gain = cfg.get("gain", 0.0)
        timeout = cfg.get("timeout", 300)

        payload = {
            "model": "IndexTTS",
            "input": text,
            "voice": voice,
            "response_format": fmt,
            "sample_rate": sample_rate,
            "stream": False,
            "speed": speed,
            "gain": gain,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(
                f"{api_url}/v1/audio/speech",
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()

            # 若输出扩展名和 response_format 不符，自动修正
            if not output_path.lower().endswith(f".{fmt}"):
                output_path = os.path.splitext(output_path)[0] + f".{fmt}"

            with open(output_path, "wb") as f:
                f.write(resp.content)

            logger.info(f"IndexTTS 完成: {output_path}")
            return output_path

        except requests.RequestException as e:
            logger.error(f"IndexTTS 调用失败: {e}")
            raise

    def _cosyvoice_tts(self, text: str, output_path: str) -> str:
        """
        调用CosyVoice2 官方FastAPI服务。

        官方端点:
          - /inference_sft        (预设说话人)
          - /inference_zero_shot  (零样本克隆)
          - /inference_instruct   (指令控制)

        返回: 流式 PCM 16bit 音频数据
        """
        cosyvoice_config = self.config["tts"]["cosyvoice"]
        api_url = cosyvoice_config["api_url"]
        mode = cosyvoice_config.get("mode", "sft")
        speaker = cosyvoice_config.get("speaker", "中文女")
        instruct_text = cosyvoice_config.get("instruct_text", "")
        sample_rate = cosyvoice_config.get("sample_rate", 22050)
        speed = cosyvoice_config.get("speed", 1.0)  # 语速，1.0=正常，<1慢，>1快

        try:
            if mode == "sft":
                # 预设说话人模式
                response = requests.post(
                    f"{api_url}/inference_sft",
                    data={"tts_text": text, "spk_id": speaker, "speed": str(speed)},
                    stream=True,
                    timeout=180,
                )
            elif mode == "instruct":
                # 指令控制模式（可控制语速、情感等）
                response = requests.post(
                    f"{api_url}/inference_instruct",
                    data={
                        "tts_text": text,
                        "spk_id": speaker,
                        "instruct_text": instruct_text,
                    },
                    stream=True,
                    timeout=180,
                )
            elif mode == "zero_shot":
                # 零样本克隆模式
                prompt_audio_path = cosyvoice_config.get("prompt_audio", "")
                prompt_text = cosyvoice_config.get("prompt_text", "")
                with open(prompt_audio_path, "rb") as audio_file:
                    response = requests.post(
                        f"{api_url}/inference_zero_shot",
                        data={
                            "tts_text": text,
                            "prompt_text": prompt_text,
                        },
                        files={"prompt_wav": audio_file},
                        stream=True,
                        timeout=180,
                    )
            else:
                raise ValueError(f"不支持的CosyVoice模式: {mode}")

            response.raise_for_status()

            # 收集流式PCM数据（CosyVoice流结束时可能抛出ChunkedEncodingError，属正常）
            pcm_data = b""
            try:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        pcm_data += chunk
            except requests.exceptions.ChunkedEncodingError:
                pass  # 流正常结束

            self._pcm_to_wav(pcm_data, output_path, sample_rate)
            logger.info(f"CosyVoice TTS完成: {output_path}")
            return output_path

        except requests.RequestException as e:
            logger.warning(f"CosyVoice调用失败: {e}，尝试edge-tts备用")
            return self._edge_tts(text, output_path)

    def _pcm_to_wav(self, pcm_data: bytes, output_path: str, sample_rate: int):
        """将原始PCM 16bit数据转为WAV文件"""
        with wave.open(output_path, "wb") as wav_file:
            wav_file.setnchannels(1)       # 单声道
            wav_file.setsampwidth(2)       # 16bit = 2 bytes
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)

    def _edge_tts(self, text: str, output_path: str) -> str:
        """使用edge-tts作为备用方案"""
        import edge_tts

        edge_config = self.config["tts"]["edge_tts"]
        voice = edge_config["voice"]
        rate = edge_config.get("rate", "+0%")     # 如 "-20%" 慢 20%, "+10%" 快 10%
        pitch = edge_config.get("pitch", "+0Hz")  # 如 "-5Hz" 低沉, "+5Hz" 尖锐
        volume = edge_config.get("volume", "+0%")

        async def _generate():
            communicate = edge_tts.Communicate(
                text, voice, rate=rate, pitch=pitch, volume=volume
            )
            await communicate.save(output_path)

        asyncio.run(_generate())
        logger.info(f"Edge-TTS完成: {output_path}")
        return output_path

    def is_available(self) -> bool:
        """检查TTS服务是否可用"""
        if self.engine == "cosyvoice":
            try:
                api_url = self.config["tts"]["cosyvoice"]["api_url"]
                # 官方FastAPI服务没有专门的health端点，尝试连接根路径
                resp = requests.get(api_url, timeout=5)
                return resp.status_code in (200, 404, 405)
            except requests.RequestException:
                return False
        return True
