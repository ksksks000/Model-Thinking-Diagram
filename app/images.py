"""从 PDF 里提取要识别的图片（pymupdf）。

两种来源：
  · 纯截图页(blank) → 整页渲染 page_pixmap()，内容就是整页，还能兜矢量元素
  · 有正文/标签但有嵌图的页 → 取内嵌位图 page_images()，保留原像素、体积小，
    且不会把已有文字层再识别一遍
都用「够大」过滤小图标/装饰线；同 xref（同一张图被多页复用）只取一次。
"""
import pymupdf

# 过滤阈值：太小当图标/装饰，跳过
MIN_W = 100
MIN_H = 100
MIN_AREA = 12000          # 100*120 左右
MAX_PER_PAGE = 5          # 每页识别上限，防个别怪页爆炸


def _is_big(info: dict) -> bool:
    w = info.get("width") or 0
    h = info.get("height") or 0
    return w >= MIN_W and h >= MIN_H and (w * h) >= MIN_AREA


def page_images(doc: pymupdf.Document, page: pymupdf.Page,
                max_per_page: int = MAX_PER_PAGE) -> list[bytes]:
    """取一页里「够大的内嵌位图」的原始字节（PNG/JPEG）。同 xref 去重。"""
    out = []
    seen = set()
    try:
        for xref, *_ in page.get_images(full=True):
            if xref in seen:
                continue
            seen.add(xref)
            info = doc.extract_image(xref)
            if not info or not _is_big(info):
                continue
            out.append(info["image"])     # 原始编码字节（PNG 或 JPEG）
            if len(out) >= max_per_page:
                break
    except Exception:
        return out
    return out


def page_pixmap_bytes(page: pymupdf.Page, dpi: int = 200) -> bytes:
    """整页渲染成 PNG 字节（空白页/矢量元素兜底用）。"""
    try:
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    except Exception:
        return b""


def candidates(doc: pymupdf.Document, blank_pages: list[int]) -> dict[int, list[bytes]]:
    """返回要识别的页 → 图片字节列表。

    blank 页：整页渲染（1 张整页图）。
    其它页：只取够大的内嵌位图。
    空 dict 表示没有可识别的页。
    """
    out: dict[int, list[bytes]] = {}
    total = doc.page_count
    blank_set = set(blank_pages)
    try:
        for pno in range(1, total + 1):
            page = doc[pno - 1]
            imgs = []
            if pno in blank_set:
                whole = page_pixmap_bytes(page)
                if whole:
                    imgs.append(whole)
            else:
                imgs = page_images(doc, page)
            if imgs:
                out[pno] = imgs
    except Exception:
        pass
    return out