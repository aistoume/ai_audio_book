"""文本分块工具 - 把长文本按标点符号切成适合 TTS 的小段"""

import re


# 中英文句末标点（强断点）
_SENT_ENDS = "。！？!?……"
# 弱断点（逗号、分号等）
_SOFT_ENDS = "，,；;：:"


def split_text_for_tts(text: str, max_chars: int = 300, min_chars: int = 50) -> list[str]:
    """
    将长文本切分为 TTS 友好的片段。

    策略：
      1. 按段落先粗分
      2. 段落超长时按句号拆分
      3. 仍超长时按逗号拆分
      4. 过短的片段会与相邻片段合并

    Args:
        text: 原始文本
        max_chars: 每段目标最大字符数（超过会尝试切分）
        min_chars: 过短合并阈值

    Returns:
        list[str]: 切分后的文本段列表
    """
    # 1. 清理：合并多余空白，但保留段落换行
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 2. 按段落先粗分（双换行）
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    # 3. 对每段做细切
    chunks = []
    for para in paragraphs:
        # 把单行换行替换为空格（同一段内）
        para = re.sub(r"\s*\n\s*", " ", para).strip()
        if not para:
            continue
        if len(para) <= max_chars:
            chunks.append(para)
        else:
            chunks.extend(_split_long_paragraph(para, max_chars))

    # 4. 合并过短片段
    return _merge_short_chunks(chunks, min_chars, max_chars)


def _split_long_paragraph(para: str, max_chars: int) -> list[str]:
    """把一个超长段落按句末标点切分"""
    # 用正则保留标点
    sentences = re.split(f"([{_SENT_ENDS}])", para)

    # 成对合并（内容 + 标点）
    merged = []
    buf = ""
    for part in sentences:
        buf += part
        if part and part[-1] in _SENT_ENDS:
            merged.append(buf.strip())
            buf = ""
    if buf.strip():
        merged.append(buf.strip())

    # 如果单句仍超长，退化用逗号切
    result = []
    for s in merged:
        if len(s) <= max_chars:
            result.append(s)
        else:
            result.extend(_split_by_soft(s, max_chars))
    return result


def _split_by_soft(s: str, max_chars: int) -> list[str]:
    """用逗号等弱断点切，还是超长就硬切"""
    parts = re.split(f"([{_SOFT_ENDS}])", s)
    merged = []
    buf = ""
    for part in parts:
        if len(buf) + len(part) > max_chars and buf:
            merged.append(buf.strip())
            buf = part
        else:
            buf += part
    if buf.strip():
        merged.append(buf.strip())

    # 最后兜底：硬切
    result = []
    for m in merged:
        while len(m) > max_chars:
            result.append(m[:max_chars])
            m = m[max_chars:]
        if m:
            result.append(m)
    return result


def _merge_short_chunks(chunks: list[str], min_chars: int, max_chars: int) -> list[str]:
    """把过短的段合并到相邻段"""
    if not chunks:
        return chunks
    merged = []
    buf = ""
    for c in chunks:
        if len(buf) + len(c) + 1 <= max_chars and (len(buf) < min_chars or len(c) < min_chars):
            buf = (buf + " " + c).strip() if buf else c
        else:
            if buf:
                merged.append(buf)
            buf = c
    if buf:
        merged.append(buf)
    return merged
