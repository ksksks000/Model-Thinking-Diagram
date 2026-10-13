"""转换管线编排：体检 → 抽字 → Claude → 校验 → 版本号命名 → 登记 index.json。

进度经 job.update() 上报，SSE 端点从内存 job 表读。全程在后台线程跑。

BM: D:/oneone/app/converter.py
"""
import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

import portalocker

from .checker import check, extract_pages
from . import llm
from .prompts.system_prompt import build_system_prompt
from .settings import APP_DIR, MAX_TURN_TOKENS

ROOT = APP_DIR.parent
NOTES_DIR = ROOT / "notes"
INDEX_FILE = NOTES_DIR / "index.json"
TEMP_DIR = APP_DIR / "temps"          # 上传的 PDF 和 raw.txt 临时落这里
STYLE_DEPTHS = {"A": 6, "B": 4}       # 最深缩进（空格数）

# <base> 只留 ASCII，别把中文"清洗"成空串再兜底成 imported（旧版踩过的坑）
SAFE_BASE_RE = re.compile(r"[\\/:*?\"<>|\s]+")


def sanitize_base(name: str) -> str:
    stem = Path(name).stem
    base = SAFE_BASE_RE.sub("-", stem).strip("-").lower() or "note"
    return base[:40] or "note"


def pick_version_path(base: str) -> Path:
    """notes\\<base>-<YYYYMMDD>.md；同日第二版起补时分（<base>-<YYYYMMDD>-<HHMM>）。"""
    today = datetime.now().strftime("%Y%m%d")
    NOTES_DIR.mkdir(exist_ok=True)
    plain = NOTES_DIR / f"{base}-{today}.md"
    if not plain.exists():
        return plain
    # 已有同日无时分版：两个都补上时分（早的那个也改名，别一半带一半不带）
    hhmm = datetime.now().strftime("%H%M")
    old = NOTES_DIR / f"{base}-{today}-{hhmm}.md"
    plain.rename(old)
    reindex_rename(f"{base}-{today}", f"{base}-{today}-{hhmm}")
    return old


def reindex_rename(old_id: str, new_id: str):
    """index.json 里同步改 id/file，别丢链。"""
    with_index_lock(lambda: _reindex_rename_locked(old_id, new_id))


def _reindex_rename_locked(old_id: str, new_id: str):
    if not INDEX_FILE.exists():
        return
    data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    for t in data.get("trees", []):
        if t.get("id") == old_id:
            t["id"] = new_id
            t["file"] = f"notes/{new_id}.md"
            t["title"] = re.sub(r"\d{2}-\d{2} \d{2}:\d{2}", "", t.get("title", "")).strip()
    INDEX_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


_INDEX_LOCK = threading.Lock()


def with_index_lock(fn):
    """进程内锁 + 文件锁（portalocker），防连发两单同时写 index。

    锁必须是独立的 .lock 文件——要是在 index.json 本体上开 a+ 加锁，
    Windows 会拒绝随后 os.replace 覆盖这个还开着的文件。
    """
    with _INDEX_LOCK:
        INDEX_FILE.parent.mkdir(exist_ok=True)
        lock_path = INDEX_FILE.with_suffix(".json.lock")
        with open(lock_path, "a", encoding="utf-8") as fh:
            portalocker.lock(fh, portalocker.LOCK_EX)
            try:
                return fn()
            finally:
                portalocker.unlock(fh)


def finalize_note(job, md: str, check_info: dict) -> dict:
    """校验 → 命名 → 落盘 → 登记。返回 {id, title, file, gaps}。"""
    style = job.style.upper()
    gaps = parse_gaps(md)
    path = pick_version_path(sanitize_base(job.filename))
    path.write_text(md, encoding="utf-8")

    note_id = path.stem
    ts = datetime.now()
    title = f"{Path(job.filename).stem} {ts.strftime('%m-%d %H:%M')}"

    def _register():
        data = {"trees": []}
        if INDEX_FILE.exists():
            data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        entry = {"id": note_id, "title": title, "file": f"notes/{note_id}.md"}
        if gaps:
            entry["gaps"] = gaps
        data.setdefault("trees", [])
        data["trees"].insert(0, entry)   # 新版排前面
        tmp = INDEX_FILE.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(INDEX_FILE)          # 原子替换

    with_index_lock(_register)
    return {"id": note_id, "title": title, "file": f"notes/{note_id}.md", "gaps": gaps}


def parse_gaps(md: str) -> list[str]:
    """抽 ## 待补充 下的非空行作缺口列表。"""
    m = re.search(r"^##\s*待补充\s*$", md, re.M)
    if not m:
        return []
    out = []
    for line in md[m.end():].splitlines():
        s = line.strip()
        if s.startswith("#"):
            break
        if s.startswith("-"):
            out.append(s.lstrip("- "))
    return out


def validate(md: str, style: str) -> list[str]:
    """机械校验。只兜机器兜得住的，文风保真靠样例锚 + 人工抽查。"""
    errs = []
    if not md.lstrip().startswith("# "):
        errs.append("首行不是 # 标题")
    if "## 待补充" not in md:
        errs.append("缺 ## 待补充 段")
    max_indent = STYLE_DEPTHS.get(style.upper(), 6)
    for i, line in enumerate(md.splitlines(), 1):
        stripped = line.lstrip(" ")
        if not stripped:
            continue
        indent = len(line) - len(stripped)
        if indent % 2 != 0:
            errs.append(f"第 {i} 行缩进 {indent} 空格，不是偶数")
        if indent > max_indent:
            errs.append(f"第 {i} 行缩进 {indent} 空格，超过风格 {style} 上限 {max_indent}")
    return errs


# ── Claude 调用 ───────────────────────────────────────────────────


def split_batches(raw: str, max_chars: int) -> list[str]:
    """长文按 ===== PAGE N ===== 切成若干批（不是按原文 ## ——PDF 文字层无 md 标题）。
    每批尽量接近 max_chars，减少批数即减少文风漂移面。"""
    pages = [p for p in raw.split("===== PAGE ") if p.strip()]
    batches, buf = [], []
    size = 0
    for p in pages:
        chunk = "===== PAGE " + p
        if buf and size + len(chunk) > max_chars:
            batches.append("".join(buf))
            buf, size = [], 0
        buf.append(chunk)
        size += len(chunk)
    if buf:
        batches.append("".join(buf))
    return batches


BATCH_CHARS = 30000   # 每批约 3 万字符（≈ 1.5 万 token），38 页实测 2 批


def draft_title(md: str, fallback: str) -> str:
    return (md.lstrip().splitlines() or ["# " + fallback])[0].lstrip("# ").strip()


def run(job) -> None:
    """管线主体。异常一律上抛由调用方 catch；失败也必须 finish 事件。"""
    try:
        pdf_path = TEMP_DIR / job.filename
        job.update(phase="check", message="正在体检 PDF…")
        info = check(str(pdf_path))
        job.result_check = info

        # 逐页抽文字层（数组，方便后面按页并入识图结果）
        job.update(phase="extract", message=f"抽文字（{info['total']} 页）…")
        pages = extract_pages(str(pdf_path))

        # 图片识别：blank 页整页渲染，其余含「够大嵌图」的页取内嵌位图
        ocr_pages = []
        try:
            import pymupdf
            from . import images, vision
            job.update(phase="vision", message="识别页内图片…")
            with pymupdf.open(str(pdf_path)) as doc:
                cand = images.candidates(doc, info.get("blank") or [])
            for pno in sorted(cand):
                imgs = cand[pno]
                extra = vision.pages_result(pno, imgs)
                if not extra:
                    continue
                ocr_pages.append(pno)
                if 0 <= pno - 1 < len(pages):
                    pages[pno - 1] = (pages[pno - 1] + "\n\n" + extra).strip()
        except Exception:
            pass   # 识图是增强，失败不应中断主流程
        if ocr_pages:
            job.update(message=f"识别了 {len(ocr_pages)} 个页面的图片")

        # 组装成带页码标记的全文；「几乎抽不出文字」的判定必须在并入识图结果之后
        raw = "\n\n".join(
            f"===== PAGE {i} =====\n{t}" for i, t in enumerate(pages, 1)
        )
        if len(raw.strip()) < 50:
            raise RuntimeError("这份 PDF 几乎抽不出文字（抽字+识图后仍为空），没法整理")

        if not llm.get_api_key():
            raise RuntimeError("没有配置 API key。去右上角「⚙ 设置」填。")

        job.update(phase="ai", progress=5, message=f"{llm.channel_label()} 整理中…")
        system = build_system_prompt(job.style)

        batches = split_batches(raw, BATCH_CHARS)
        parts = []
        for bi, batch in enumerate(batches, 1):
            pct_base = 5 + (bi - 1) * (90 // len(batches))
            pct_step = 90 // len(batches)
            prefix = (
                "" if bi == 1 else
                "这是同一份笔记的后续批次，延续同一份风格与板块划分，"
                "遇到上一批末尾断掉的句子/条目，接上再整理。\n\n"
            )
            text = llm.complete(
                system,
                prefix
                + "下面是 PDF 的文字层原文。请按规范整理成思维导图笔记。\n\n"
                + batch,
                MAX_TURN_TOKENS,
            )
            parts.append(text)
            job.update(
                phase="ai",
                progress=min(95, pct_base + pct_step),
                message=f"{llm.channel_label()} 整理中（批次 {bi}/{len(batches)}）…",
            )

        md = ("\n\n" if len(parts) > 1 else "").join(p.strip() for p in parts)
        errs = validate(md, job.style)
        if errs:
            job.update(message=f"机械校验告警 {'; '.join(errs[:3])}")

        job.update(phase="save", message="登记 index.json…")
        result = finalize_note(job, md, info)
        if ocr_pages:
            result["ocr_pages"] = ocr_pages
        job.result = result
        job.update(phase="done", progress=100, message="完成 ✓")

        # 清理本次的临时文件
        for f in (pdf_path, TEMP_DIR / f"_{Path(job.filename).stem}.raw.txt"):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
    except Exception as exc:                       # noqa: BLE001 —— 后台线程统一兜底
        job.error = str(exc)
        job.update(phase="error", message=str(exc))
    finally:
        from .jobs import finish
        finish(job.id)
