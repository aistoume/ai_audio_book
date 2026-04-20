"""LLM处理模块 - 使用Gemini/Claude进行文本分析和提示词生成"""

import json
import logging

from google import genai

logger = logging.getLogger(__name__)


class LLMProcessor:
    def __init__(self, config: dict):
        self.config = config
        self.provider = config["llm"]["provider"]

        if self.provider == "gemini":
            self.client = genai.Client(api_key=config["llm"]["gemini"]["api_key"])
            self.model_name = config["llm"]["gemini"]["model"]
        else:
            raise ValueError(f"暂不支持的LLM provider: {self.provider}")

    def split_into_chapters(self, text: str, title: str) -> list[dict]:
        """
        将全文分割为章节/段落。

        Returns:
            list[dict]: [{"chapter": 章节标题, "content": 章节内容}, ...]
        """
        prompt = f"""你是一个书籍分析助手。请将以下书籍文本分割成合理的章节或段落。

书名: {title}

要求:
1. 如果文本本身有明确的章节标题，按原有章节分割
2. 如果没有明确章节，按主题/内容逻辑分段，每段300-800字
3. 为每个段落给出简短的章节标题

请以JSON格式返回，格式如下:
[
  {{"chapter": "章节标题", "content": "章节完整内容"}},
  ...
]

只返回JSON，不要其他内容。

--- 书籍文本 ---
{text[:15000]}
"""
        response = self._call_llm(prompt)
        return self._parse_json_response(response)

    def generate_narration_and_prompts(self, chapters: list[dict]) -> list[dict]:
        """
        为每个章节生成旁白文本和图片描述prompt。

        Returns:
            list[dict]: [{"chapter": ..., "narration": 旁白, "image_prompt": 英文图片描述}, ...]
        """
        results = []
        for chapter in chapters:
            result = self._process_single_chapter(chapter)
            results.append(result)
        return results

    def _process_single_chapter(self, chapter: dict) -> dict:
        """处理单个章节，生成旁白和图片prompt"""
        prompt = f"""你是一个创意内容助手。请根据以下书籍章节内容，完成两个任务:

章节标题: {chapter['chapter']}
章节内容: {chapter['content']}

任务1: 生成适合语音朗读的旁白文本（中文，口语化，自然流畅，200-400字）
任务2: 生成一段英文图片描述prompt，用于AI绘图工具生成配图（描述场景、氛围、风格，50-100词）

请以JSON格式返回:
{{
  "narration": "中文旁白文本...",
  "image_prompt": "English image description for AI art generation..."
}}

只返回JSON，不要其他内容。"""

        response = self._call_llm(prompt)
        parsed = self._parse_json_response(response)

        return {
            "chapter": chapter["chapter"],
            "content": chapter["content"],
            "narration": parsed.get("narration", chapter["content"][:400]),
            "image_prompt": parsed.get("image_prompt", "a beautiful book illustration, digital art"),
        }

    def _call_llm(self, prompt: str) -> str:
        """调用LLM API"""
        if self.provider == "gemini":
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            return response.text
        raise ValueError(f"不支持的provider: {self.provider}")

    def _parse_json_response(self, response: str) -> list | dict:
        """解析LLM返回的JSON"""
        # 清理可能的markdown代码块标记
        text = response.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}\n原始响应: {text[:500]}")
            return [{"chapter": "全文", "content": text}] if "[" in response else {"narration": text, "image_prompt": "book illustration"}
