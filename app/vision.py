"""图片识别编排：按 VISION_MODE 在「本地 OCR」和「多模态视觉」间选择/回退。

模式（settings.get_vision_mode()）：
  off     → 跳过，不识别
  ocr     → 只用本地 rapidocr（免费）
  vision  → 只用视觉模型（按量计费，需要通道支持多模态）
  auto    → 先本地 OCR；识别结果过短（疑手写/图表/代码）才调视觉模型

安全：单页识别任何失败都不外抛——返回可用的识别文本，
两者都失败则返回固定占位，让「图片没识别成功」可见而非静默丢失。
"""
from . import llm, ocr
from .prompts.vision_ocr import VISION_OCR_PROMPT
from .settings import get_vision_mode

# 本地 OCR 结果「过短」判据：印刷中文一页通常几十行
OCR_TOO_SHORT = 20
# 视觉识别预算（max_tokens）：识别文字通常远小于整理，给足但不过分
VISION_MAX_TOKENS = 4000
# 识别结果为空/失败的标记：让「图片没识别成功」可见，而非静默丢失
FAIL_MARK = "[本页图片识别失败，请人工查看]"


def _ocr_text(imgs: list[bytes]) -> str:
    """本地 OCR 逐张识别，拼成一段。"""
    parts = []
    for b in imgs:
        t = ocr.recognize(b)
        if t.strip():
            parts.append(t)
    return "\n".join(parts)


def _vision_text(imgs: list[bytes]) -> str:
    """视觉模型一次识别整页（所有图一起塞）。"""
    if not llm.vision_available():
        return ""
    return llm.complete_vision(VISION_OCR_PROMPT, "", imgs, VISION_MAX_TOKENS)


def recognize_page(page_no: int, imgs: list[bytes]) -> str:
    """识别一页的图片，返回识别文本（可能为空串）。按 mode 编排，不外抛。"""
    if not imgs:
        return ""
    mode = get_vision_mode()
    if mode == "off":
        return ""

    try:
        if mode == "ocr":
            return _ocr_text(imgs)
        if mode == "vision":
            return _vision_text(imgs)

        # auto：先本地 OCR，太短（疑手写/图表/代码）才视觉
        text = _ocr_text(imgs)
        if text.strip() and len(text.strip()) >= OCR_TOO_SHORT:
            return text
        via_vision = _vision_text(imgs)
        return via_vision if via_vision.strip() else text

    except llm.LLMError:
        # 视觉通道没配/无效/模型不支持 → 回退本地 OCR（若 auto/vision 模式）
        text = _ocr_text(imgs)
        return text if text.strip() else ""
    except Exception:
        # 其它任何异常：本地还活着就兜底
        text = _ocr_text(imgs)
        return text if text.strip() else ""


def pages_result(page_no: int, imgs: list[bytes]) -> str:
    """给一页产出「并回 raw 的那段」文本：
       - imgs 为空 → 返回空串（这页没有要识别的图，不补）
       - 识别出文字 → "[本页图片识别]\n<文字>"
       - 识别结果为空 → FAIL_MARK，让图片识别失败可见
    """
    if not imgs or get_vision_mode() == "off":
        return ""
    text = recognize_page(page_no, imgs)
    if text.strip():
        return "[本页图片识别]\n" + text.strip()
    return FAIL_MARK