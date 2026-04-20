"""AIBook - 书籍转语音视频系统 主入口

用法:
    # 1. 单本处理（书名或完整路径）
    python main.py --book 阿甘正传.pdf
    python main.py --book "F:/Development/AIBook/books/阿甘正传.pdf"

    # 2. 批量处理（从txt文件读取书名列表，每行一个）
    python main.py --list batch.txt

    # 3. 全部处理（books/目录下所有书）
    python main.py --all

    # 覆盖模式（跳过已存在检查，强制重新生成）
    python main.py --all --overwrite
    python main.py --book 阿甘正传.pdf --overwrite

    # 不询问，默认跳过已存在的
    python main.py --all --skip-existing

    # 临时换音色（不改 config.yaml）
    python main.py --book 阿甘正传.pdf --voice example1 --overwrite
    python main.py --book 阿甘正传.pdf --voice mo_chi --speed 0.9 --overwrite
"""

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path

import yaml

from src.extractor import extract_text, scan_books_dir
from src.tts_engine import TTSEngine
from src.text_splitter import split_text_for_tts
from src.audio_merger import merge_audio_files

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("aibook.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("AIBook")


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_progress_file(book_output_dir: str) -> str:
    return os.path.join(book_output_dir, "progress.json")


def load_progress(book_output_dir: str) -> dict:
    progress_file = get_progress_file(book_output_dir)
    if os.path.exists(progress_file):
        with open(progress_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_steps": {}}


def save_progress(book_output_dir: str, progress: dict):
    progress_file = get_progress_file(book_output_dir)
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# 输入解析：把各种用户输入（书名、文件名、完整路径）解析成真实文件路径
# --------------------------------------------------------------------------
def resolve_book_path(book_input: str, books_dir: str) -> str | None:
    """
    将用户提供的书籍标识解析为实际文件或文件夹路径。

    支持：
      - 完整路径文件: "F:/Development/AIBook/books/阿甘正传.pdf"
      - 完整路径文件夹: "F:/Development/AIBook/books/某小说集/"
      - 带扩展名文件名: "阿甘正传.pdf"
      - 不带扩展名的书名: "阿甘正传" (自动匹配 .pdf/.txt 或同名文件夹)
      - 子文件夹名: "某小说集"
    """
    p = Path(book_input)

    # 1. 完整路径存在（文件或文件夹）
    if p.exists():
        return str(p.resolve())

    # 2. 相对于 books_dir
    candidate = Path(books_dir) / book_input
    if candidate.exists():
        return str(candidate.resolve())

    # 3. 不带扩展名：先尝试同名文件夹，再尝试 .pdf/.txt
    if not p.suffix:
        folder = Path(books_dir) / book_input
        if folder.is_dir():
            return str(folder.resolve())
        for ext in (".pdf", ".txt"):
            c = Path(books_dir) / f"{book_input}{ext}"
            if c.is_file():
                return str(c.resolve())

    return None


def read_book_list(list_file: str) -> list[str]:
    """从txt文件读取书名列表，每行一个，#开头为注释，空行忽略"""
    items = []
    with open(list_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                items.append(line)
    return items


# --------------------------------------------------------------------------
# 已存在检测 + 交互式确认覆盖
# --------------------------------------------------------------------------
def find_final_audio(book_output_dir: str) -> str | None:
    """查找最终的完整音频文件（如果已存在）"""
    for ext in (".mp3", ".wav", ".ogg"):
        candidate = os.path.join(book_output_dir, f"audiobook{ext}")
        if os.path.isfile(candidate):
            return candidate
    return None


def output_exists(book_output_dir: str) -> bool:
    """判断该书的最终音频是否已生成"""
    return find_final_audio(book_output_dir) is not None


def ask_overwrite(title: str, existing_path: str) -> str:
    """
    交互询问用户如何处理已存在的输出。

    Returns:
        "overwrite": 删除并重新生成
        "skip":      跳过整本书
        "resume":    保留现有 chunk 音频，继续未完成的合成（断点续传）
    """
    print()
    print(f"⚠️  '{title}' 已存在完整音频: {existing_path}")
    print("    [o] overwrite  删除旧输出，重新生成全部")
    print("    [r] resume     保留已生成的分段，继续未完成部分 (默认)")
    print("    [s] skip       跳过这本书")
    choice = input("请选择 [o/r/s] (默认 r): ").strip().lower()
    if choice == "o":
        return "overwrite"
    elif choice == "s":
        return "skip"
    else:
        return "resume"


def wipe_output(book_output_dir: str):
    """清空某本书的输出目录"""
    if os.path.isdir(book_output_dir):
        shutil.rmtree(book_output_dir)
        logger.info(f"已清空: {book_output_dir}")


# --------------------------------------------------------------------------
# 主流程（纯朗读模式 - 整本书生成一个完整音频文件）
# --------------------------------------------------------------------------
def process_book(book_path: str, config: dict, overwrite_mode: str = "ask") -> bool:
    """
    处理单本书籍：提取原文 → 按标点分块 → TTS逐块合成 → 合并为一个完整音频文件。
    不使用 LLM 做任何总结或改写，保持原文逐字朗读。

    Returns:
        bool: True=成功完成, False=跳过或失败
    """
    logger.info(f"========== 开始处理: {book_path} ==========")

    # --- 第1步: 提取原始文本 ---
    logger.info("[1/3] 提取原始文本...")
    book_data = extract_text(book_path)
    title = book_data["title"]
    text = book_data["text"]
    logger.info(f"书名: {title}, 文本长度: {len(text)} 字符")

    if not text.strip():
        logger.error(f"文本为空，跳过: {book_path}")
        return False

    book_output_dir = os.path.join(config["processing"]["output_dir"], title)

    # --- 检查已存在输出 ---
    if output_exists(book_output_dir):
        existing = find_final_audio(book_output_dir)
        if overwrite_mode == "ask":
            decision = ask_overwrite(title, existing)
        else:
            decision = overwrite_mode

        if decision == "skip":
            logger.info(f"跳过（已存在完整音频）: {title}")
            return False
        elif decision == "overwrite":
            logger.info("覆盖模式：清空旧输出...")
            wipe_output(book_output_dir)
        # resume 模式：保留已生成的分段音频，继续未完成的部分

    os.makedirs(book_output_dir, exist_ok=True)

    # 进度跟踪
    progress = load_progress(book_output_dir)
    completed = progress["completed_steps"]

    # --- 第2步: 文本分块 + TTS 逐块合成 ---
    proc = config.get("processing", {})
    max_chars = proc.get("max_chars_per_segment", 300)
    min_chars = proc.get("min_chars_per_segment", 50)

    chunks_file = os.path.join(book_output_dir, "chunks.json")
    if os.path.isfile(chunks_file) and "chunks" in completed:
        logger.info("[2/3] 文本分块缓存已存在，加载...")
        with open(chunks_file, "r", encoding="utf-8") as f:
            chunks = json.load(f)
    else:
        logger.info(f"[2/3] 文本分块（max={max_chars}, min={min_chars}字）...")
        chunks = split_text_for_tts(text, max_chars=max_chars, min_chars=min_chars)
        logger.info(f"共切分为 {len(chunks)} 个片段")
        with open(chunks_file, "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)
        completed["chunks"] = True
        save_progress(book_output_dir, progress)

    logger.info("TTS 逐块合成...")
    tts = TTSEngine(config)
    audio_dir = os.path.join(book_output_dir, "audio_chunks")
    os.makedirs(audio_dir, exist_ok=True)

    # 决定音频分段格式（尽量与最终输出一致以加速合并）
    final_fmt = config.get("audio", {}).get("output_format", "mp3").lower()
    chunk_ext = _pick_chunk_ext(config)

    chunk_paths = []
    for i, chunk in enumerate(chunks):
        step_key = f"tts_{i}"
        chunk_path = os.path.join(audio_dir, f"{i:04d}{chunk_ext}")

        if step_key in completed and os.path.exists(chunk_path):
            logger.info(f"  [{i+1}/{len(chunks)}] 已完成，跳过")
            chunk_paths.append(chunk_path)
            continue

        preview = chunk[:30].replace("\n", " ")
        logger.info(f"  [{i+1}/{len(chunks)}] {preview}...")
        try:
            actual_path = tts.synthesize(chunk, chunk_path)
            chunk_paths.append(actual_path)
            completed[step_key] = True
            save_progress(book_output_dir, progress)
        except Exception as e:
            logger.error(f"  [{i+1}] TTS 合成失败: {e}")
            continue

    if not chunk_paths:
        logger.error("所有片段都合成失败，无法合并")
        return False

    # --- 第3步: 合并为完整音频文件 ---
    gap_ms = config.get("audio", {}).get("gap_ms", 300)
    final_path = os.path.join(book_output_dir, f"audiobook.{final_fmt}")

    logger.info(f"[3/3] 合并 {len(chunk_paths)} 个片段为完整音频...")
    try:
        merge_audio_files(chunk_paths, final_path, gap_ms=gap_ms)
    except Exception as e:
        logger.error(f"合并失败: {e}")
        return False

    logger.info(f"========== 完成: {title} ==========")
    logger.info(f"最终音频: {final_path}")
    return True


def _pick_chunk_ext(config: dict) -> str:
    """根据 TTS 引擎决定分段文件扩展名"""
    engine = config["tts"]["engine"]
    if engine == "indextts":
        fmt = config["tts"]["indextts"].get("response_format", "wav")
        return f".{fmt}"
    if engine == "edge_tts":
        return ".mp3"
    return ".wav"  # cosyvoice 和默认


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="AIBook - 书籍转语音视频系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  python main.py --book 阿甘正传.pdf              单本处理
  python main.py --book F:/path/to/book.pdf       完整路径
  python main.py --list batch.txt                 批量处理 (每行一个书名)
  python main.py --all                            处理 books/ 下所有书
  python main.py --all --overwrite                强制覆盖已有输出
  python main.py --all --skip-existing            跳过已存在的
  python main.py --book xxx.pdf --voice example1  临时换音色（不改配置文件）
  python main.py --book xxx.pdf --voice alex --speed 0.9   换音色并调速
""",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--book", help="单本处理：书名或完整路径")
    mode.add_argument("--list", dest="list_file", help="批量处理：包含书名列表的txt文件")
    mode.add_argument("--all", action="store_true", help="处理 books/ 目录下所有书")

    overwrite = parser.add_mutually_exclusive_group()
    overwrite.add_argument("--overwrite", action="store_true", help="强制覆盖已有输出")
    overwrite.add_argument("--skip-existing", action="store_true", help="跳过已存在的输出")
    overwrite.add_argument("--resume", action="store_true", help="继续未完成的部分（默认行为）")

    # TTS 运行时参数（覆盖 config.yaml）
    parser.add_argument("--voice", help="参考音色名称，对应 IndexTTS characters/{voice}.wav，覆盖配置")
    parser.add_argument("--speed", type=float, help="语速，1.0=正常，0.9=慢10%%，1.1=快10%%")
    parser.add_argument("--engine", choices=["indextts", "gpt_sovits", "cosyvoice", "edge_tts"],
                        help="TTS 引擎，覆盖配置")

    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config()
    books_dir = config["processing"]["books_dir"]

    # 应用命令行覆盖到 config（不写回文件，仅本次运行生效）
    if args.engine:
        config["tts"]["engine"] = args.engine
        logger.info(f"[覆盖] TTS 引擎: {args.engine}")
    engine = config["tts"]["engine"]
    if args.voice:
        if engine not in config["tts"]:
            config["tts"][engine] = {}
        config["tts"][engine]["voice"] = args.voice
        # cosyvoice 用 speaker 字段
        if engine == "cosyvoice":
            config["tts"]["cosyvoice"]["speaker"] = args.voice
        logger.info(f"[覆盖] 音色: {args.voice}")
    if args.speed is not None:
        if engine == "indextts":
            config["tts"]["indextts"]["speed"] = args.speed
        elif engine == "gpt_sovits":
            config["tts"]["gpt_sovits"]["speed_factor"] = args.speed
        elif engine == "cosyvoice":
            config["tts"]["cosyvoice"]["speed"] = args.speed
        logger.info(f"[覆盖] 语速: {args.speed}")

    os.makedirs(books_dir, exist_ok=True)
    os.makedirs(config["processing"]["output_dir"], exist_ok=True)

    # 确定覆盖模式
    if args.overwrite:
        overwrite_mode = "overwrite"
    elif args.skip_existing:
        overwrite_mode = "skip"
    elif args.resume:
        overwrite_mode = "resume"
    else:
        overwrite_mode = "ask"

    # 收集待处理书籍路径
    book_paths = []

    if args.book:
        path = resolve_book_path(args.book, books_dir)
        if not path:
            logger.error(f"找不到书籍: {args.book}")
            logger.error(f"已在 {books_dir}/ 下搜索，请检查文件名或提供完整路径")
            sys.exit(1)
        book_paths.append(path)

    elif args.list_file:
        if not os.path.isfile(args.list_file):
            logger.error(f"列表文件不存在: {args.list_file}")
            sys.exit(1)
        names = read_book_list(args.list_file)
        logger.info(f"从 {args.list_file} 读取到 {len(names)} 个条目")
        for name in names:
            path = resolve_book_path(name, books_dir)
            if path:
                book_paths.append(path)
            else:
                logger.warning(f"找不到，跳过: {name}")

    elif args.all:
        book_paths = scan_books_dir(books_dir)

    if not book_paths:
        logger.error("没有待处理的书籍。")
        sys.exit(1)

    logger.info(f"共 {len(book_paths)} 本书待处理:")
    for p in book_paths:
        logger.info(f"  - {p}")
    logger.info(f"覆盖模式: {overwrite_mode}")

    # 逐本处理
    success = 0
    for book_path in book_paths:
        try:
            if process_book(book_path, config, overwrite_mode):
                success += 1
        except Exception as e:
            logger.error(f"处理 {book_path} 时出错: {e}", exc_info=True)
            continue

    logger.info(f"全部完成！成功 {success} / {len(book_paths)} 本")


if __name__ == "__main__":
    main()
