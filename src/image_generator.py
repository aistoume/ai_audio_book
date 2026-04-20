"""图片生成模块 - 通过ComfyUI API生成配图 (Z-Image-Turbo)"""

import json
import logging
import os
import time
import urllib.parse

import requests

logger = logging.getLogger(__name__)


class ImageGenerator:
    def __init__(self, config: dict):
        self.config = config
        comfy = config["comfyui"]
        self.api_url = comfy["api_url"]
        self.width = comfy["width"]
        self.height = comfy["height"]
        self.steps = comfy["steps"]
        self.cfg_scale = comfy["cfg_scale"]
        self.sampler = comfy["sampler"]
        self.scheduler = comfy["scheduler"]
        self.unet_name = comfy["unet_name"]
        self.clip_name = comfy["clip_name"]
        self.vae_name = comfy["vae_name"]
        # 超时和重试配置（可在 config.yaml 中覆盖）
        self.timeout = comfy.get("timeout", 300)        # 单次生成超时（秒）
        self.max_retries = comfy.get("max_retries", 3)  # 卡住后重试次数

        # 加载工作流模板
        workflow_path = comfy["workflow_file"]
        if os.path.exists(workflow_path):
            with open(workflow_path, "r", encoding="utf-8") as f:
                self.workflow_template_str = f.read()
        else:
            self.workflow_template_str = None
            logger.warning(f"工作流文件不存在: {workflow_path}，将使用内置默认工作流")

    def generate(self, prompt: str, output_path: str, negative_prompt: str = "") -> str:
        """
        生成图片。

        Args:
            prompt: 正向提示词（英文）
            output_path: 输出图片路径
            negative_prompt: 负向提示词（z-image-turbo使用ConditioningZeroOut，此参数忽略）

        Returns:
            str: 生成的图片文件路径
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                workflow = self._build_workflow(prompt)
                prompt_id = self._queue_prompt(workflow)
                image_data = self._wait_and_download(prompt_id, timeout=self.timeout)

                with open(output_path, "wb") as f:
                    f.write(image_data)

                logger.info(f"图片生成完成: {output_path}")
                return output_path

            except (TimeoutError, requests.RequestException) as e:
                last_err = e
                logger.warning(
                    f"图片生成失败（第 {attempt}/{self.max_retries} 次尝试）: {e}"
                )
                # 尝试取消卡住的任务，释放队列
                self._try_interrupt()
                if attempt < self.max_retries:
                    time.sleep(3)

        raise RuntimeError(
            f"图片生成彻底失败（已重试 {self.max_retries} 次）: {last_err}"
        )

    def _try_interrupt(self):
        """尝试取消ComfyUI正在执行的任务（卡住时用）"""
        try:
            requests.post(f"{self.api_url}/interrupt", timeout=5)
            logger.info("已发送 interrupt 指令给 ComfyUI")
        except Exception as e:
            logger.debug(f"interrupt 调用失败: {e}")

    def _build_workflow(self, prompt: str) -> dict:
        """构建ComfyUI工作流（Z-Image-Turbo）"""
        seed = int(time.time()) % 2**32

        if self.workflow_template_str:
            wf_str = self.workflow_template_str
            wf_str = wf_str.replace("{{POSITIVE_PROMPT}}", prompt.replace('"', '\\"'))
            wf_str = wf_str.replace("{{WIDTH}}", str(self.width))
            wf_str = wf_str.replace("{{HEIGHT}}", str(self.height))
            wf_str = wf_str.replace("{{STEPS}}", str(self.steps))
            wf_str = wf_str.replace("{{CFG}}", str(self.cfg_scale))
            wf_str = wf_str.replace("{{SAMPLER}}", self.sampler)
            wf_str = wf_str.replace("{{SCHEDULER}}", self.scheduler)
            wf_str = wf_str.replace("{{SEED}}", str(seed))
            wf_str = wf_str.replace("{{UNET_NAME}}", self.unet_name)
            wf_str = wf_str.replace("{{CLIP_NAME}}", self.clip_name)
            wf_str = wf_str.replace("{{VAE_NAME}}", self.vae_name)
            return json.loads(wf_str)

        # 内置默认工作流 (Z-Image-Turbo)
        return {
            "28": {
                "class_type": "UNETLoader",
                "inputs": {
                    "unet_name": self.unet_name,
                    "weight_dtype": "default",
                },
            },
            "30": {
                "class_type": "CLIPLoader",
                "inputs": {
                    "clip_name": self.clip_name,
                    "type": "lumina2",
                    "device": "default",
                },
            },
            "29": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": self.vae_name},
            },
            "11": {
                "class_type": "ModelSamplingAuraFlow",
                "inputs": {
                    "shift": 3,
                    "model": ["28", 0],
                },
            },
            "27": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": prompt,
                    "clip": ["30", 0],
                },
            },
            "33": {
                "class_type": "ConditioningZeroOut",
                "inputs": {"conditioning": ["27", 0]},
            },
            "13": {
                "class_type": "EmptySD3LatentImage",
                "inputs": {
                    "width": self.width,
                    "height": self.height,
                    "batch_size": 1,
                },
            },
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "control_after_generate": "randomize",
                    "steps": self.steps,
                    "cfg": self.cfg_scale,
                    "sampler_name": self.sampler,
                    "scheduler": self.scheduler,
                    "denoise": 1.0,
                    "model": ["11", 0],
                    "positive": ["27", 0],
                    "negative": ["33", 0],
                    "latent_image": ["13", 0],
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["29", 0],
                },
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": "aibook",
                    "images": ["8", 0],
                },
            },
        }

    def _queue_prompt(self, workflow: dict) -> str:
        """提交工作流到ComfyUI队列"""
        payload = {"prompt": workflow}
        response = requests.post(
            f"{self.api_url}/prompt",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["prompt_id"]

    def _wait_and_download(self, prompt_id: str, timeout: int = 300) -> bytes:
        """等待生成完成并下载图片"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            response = requests.get(
                f"{self.api_url}/history/{prompt_id}",
                timeout=10,
            )
            response.raise_for_status()
            history = response.json()

            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                for node_id, node_output in outputs.items():
                    if "images" in node_output:
                        image_info = node_output["images"][0]
                        return self._download_image(
                            image_info["filename"],
                            image_info.get("subfolder", ""),
                            image_info.get("type", "output"),
                        )

            time.sleep(2)

        raise TimeoutError(f"ComfyUI生成超时 ({timeout}秒)")

    def _download_image(self, filename: str, subfolder: str, folder_type: str) -> bytes:
        """从ComfyUI下载生成的图片"""
        params = urllib.parse.urlencode({
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type,
        })
        response = requests.get(
            f"{self.api_url}/view?{params}",
            timeout=30,
        )
        response.raise_for_status()
        return response.content

    def is_available(self) -> bool:
        """检查ComfyUI是否可用"""
        try:
            resp = requests.get(f"{self.api_url}/system_stats", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False
