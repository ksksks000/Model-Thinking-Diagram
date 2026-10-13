"""体检 + 抽文字 —— 逻辑搬自 .claude/skills/pdf2md/SKILL.md 第 1、3 步。

三档判定（剥掉页脚/时间戳后按剩余字数）：
  有正文   > 40 字  → 直接可用
  只有标签 1–40 字  → OneNote 页面标题，可当大纲节点
  真空白   0 字     → 内容 100% 在图片里
"""
import re

import pdfplumber
import pypdf

# 页脚「分区名 的第 21 页」；时间戳「2026年5月20日 16:15」
FOOT = re.compile(r".*的第\s*\d+\s*页.*")
DATE = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2}")


def check(path: str) -> dict:
    """读 PDF 统计三档页码。返回 {total, images, rich, labeled, blank}。"""
    reader = pypdf.PdfReader(path)
    rich, labeled, blank, imgs = [], [], [], 0
    for i, pg in enumerate(reader.pages, 1):
        lines = [l.strip() for l in (pg.extract_text() or "").splitlines()]
        body = " ".join(
            l for l in lines if l and not FOOT.match(l) and not DATE.match(l)
        ).strip()
        imgs += len(pg.images)
        (blank if not body else labeled if len(body) < 40 else rich).append(i)
    return {
        "total": len(reader.pages),
        "images": imgs,
        "rich": rich,
        "labeled": labeled,
        "blank": blank,
    }


def extract_pages(path: str) -> list[str]:
    """pdfplumber 逐页抽文字层，返回「每页一段」的列表（不带页码标记）。

    不用 pdftotext —— OneNote 文本框顺序不保证，pdftotext 行序会串。
    """
    out = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            out.append((pg.extract_text() or "").strip())
    return out


def extract_text(path: str) -> str:
    """抽全文，页间用 ===== PAGE N ===== 分隔（旧入口，向上兼容）。"""
    return "\n\n".join(
        f"===== PAGE {i} =====\n{t}"
        for i, t in enumerate(extract_pages(path), 1)
    )
