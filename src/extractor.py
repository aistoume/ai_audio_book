"""文本提取模块 - 从PDF/TXT文件或多卷子文件夹中提取文本"""

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = {".pdf", ".txt"}

# 中文数字映射，用于排序
_CHINESE_DIGITS = {
    "零": 0, "〇": 0, "○": 0,
    "一": 1, "壹": 1,
    "二": 2, "贰": 2, "两": 2,
    "三": 3, "叁": 3,
    "四": 4, "肆": 4,
    "五": 5, "伍": 5,
    "六": 6, "陆": 6,
    "七": 7, "柒": 7,
    "八": 8, "捌": 8,
    "九": 9, "玖": 9,
    "十": 10, "拾": 10,
    "百": 100, "千": 1000, "万": 10000,
}


def _chinese_to_int(s: str) -> int | None:
    """将简单中文数字字符串转为整数，如 '一'->1, '二十'->20, '一百零五'->105"""
    if not s or not all(c in _CHINESE_DIGITS for c in s):
        return None

    # 简单情况：单个字符
    if len(s) == 1:
        return _CHINESE_DIGITS[s]

    total = 0
    current = 0
    for ch in s:
        v = _CHINESE_DIGITS[ch]
        if v >= 10:  # 单位
            if current == 0:
                current = 1
            total += current * v
            current = 0
        else:
            current = v
    total += current
    return total


def _extract_order_key(name: str) -> tuple:
    """
    从文件名/目录名中提取排序键。
    优先级: 阿拉伯数字 > 中文数字 > 原文字符串

    示例:
      "第1卷.txt"  → (1, "第1卷.txt")
      "第一卷.txt" → (1, "第一卷.txt")
      "vol_02.pdf" → (2, "vol_02.pdf")
      "abc.txt"    → (999999, "abc.txt")
    """
    # 阿拉伯数字
    arabic = re.search(r"\d+", name)
    if arabic:
        return (int(arabic.group()), name)

    # 中文数字（提取连续的中文数字字符）
    chinese = re.search(r"[零〇○一壹二贰两三叁四肆五伍六陆七柒八捌九玖十拾百千万]+", name)
    if chinese:
        n = _chinese_to_int(chinese.group())
        if n is not None:
            return (n, name)

    # 没找到数字，放到最后
    return (999999, name)


def extract_text(path: str) -> dict:
    """
    从单个文件或包含多个文件的文件夹中提取文本。

    - 文件: 返回单个文件的内容
    - 文件夹: 按排序合并文件夹内所有支持格式的文件内容

    Returns:
        dict: {"title": 书名, "text": 全文文本, "source": 路径}
    """
    p = Path(path)

    if not p.exists():
        raise FileNotFoundError(f"路径不存在: {p}")

    if p.is_dir():
        return _extract_from_dir(p)
    elif p.is_file():
        return _extract_from_file(p)
    else:
        raise ValueError(f"未知路径类型: {p}")


def _extract_from_file(file_path: Path) -> dict:
    """从单个文件提取"""
    ext = file_path.suffix.lower()
    title = file_path.stem

    if ext == ".pdf":
        text = _extract_pdf(file_path)
    elif ext == ".txt":
        text = _extract_txt(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}")

    return {"title": title, "text": text, "source": str(file_path)}


def _extract_from_dir(dir_path: Path) -> dict:
    """从文件夹提取：扫描支持的文件，按序号排序后合并"""
    # 收集所有支持的文件（只扫第一层，不递归）
    files = [
        f for f in dir_path.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS
    ]

    if not files:
        raise ValueError(f"文件夹内没有支持的文件 (.pdf/.txt): {dir_path}")

    # 按提取的序号排序
    files.sort(key=lambda f: _extract_order_key(f.name))

    logger.info(f"'{dir_path.name}' 识别为多卷书籍，共 {len(files)} 卷，处理顺序:")
    for idx, f in enumerate(files, 1):
        logger.info(f"  卷{idx}: {f.name}")

    # 逐个提取并合并
    parts = []
    for f in files:
        try:
            if f.suffix.lower() == ".pdf":
                t = _extract_pdf(f)
            else:
                t = _extract_txt(f)
            if t.strip():
                # 在每卷开头插入卷名，便于LLM识别章节边界
                parts.append(f"【{f.stem}】\n\n{t.strip()}")
        except Exception as e:
            logger.warning(f"卷 {f.name} 提取失败，跳过: {e}")

    title = dir_path.name
    text = "\n\n".join(parts)
    return {"title": title, "text": text, "source": str(dir_path)}


def _extract_pdf(file_path: Path) -> str:
    """从PDF文件提取文本"""
    import fitz

    doc = fitz.open(str(file_path))
    pages_text = []
    for page in doc:
        t = page.get_text()
        if t.strip():
            pages_text.append(t)
    doc.close()
    return "\n".join(pages_text)


def _extract_txt(file_path: Path) -> str:
    """从TXT文件提取文本，自动检测编码"""
    for enc in ("utf-8", "gbk", "gb18030", "big5"):
        try:
            return file_path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return file_path.read_text(encoding="latin-1")


def scan_books_dir(books_dir: str) -> list[str]:
    """
    扫描书籍目录，返回所有可处理的条目：
      - 顶层的 .pdf/.txt 文件
      - 顶层的子文件夹（如果其中包含支持格式的文件）
    """
    books_path = Path(books_dir)
    if not books_path.exists():
        return []

    items = []
    for entry in sorted(books_path.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTS:
            items.append(str(entry))
        elif entry.is_dir():
            # 检查子文件夹是否包含支持的文件
            has_supported = any(
                f.is_file() and f.suffix.lower() in SUPPORTED_EXTS
                for f in entry.iterdir()
            )
            if has_supported:
                items.append(str(entry))
    return items
