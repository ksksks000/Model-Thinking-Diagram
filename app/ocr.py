"""本地 OCR 引擎封装（rapidocr 3.10，ONNX 后端）。

懒加载 + 单例：rapidocr 首次要加载/下载模型（约 18s），之后进程内复用。
所有异常内部消化，识别失败返回空串——绝不让单张图拖垮整个转换任务。
"""
import threading

_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from rapidocr import RapidOCR      # 惰性 import，避免未装时崩启动
                _engine = RapidOCR()
    return _engine


def recognize(png_bytes: bytes) -> str:
    """识别单张 PNG，返回逐行文本（每行一个，脚本按原文换行拼接）。

    引擎没装/加载失败/识别失败 → 返回空串，不抛异常。
    """
    if not png_bytes:
        return ""
    try:
        engine = _get_engine()
        res = engine(png_bytes)
        txts = getattr(res, "txts", None)
        if not txts:
            return ""
        # 逐行照抄，保留换行（OCR 行间用空行分隔，避免挤成一句）
        return "\n".join(t.strip() for t in txts if t and t.strip())
    except Exception:
        return ""


def available() -> bool:
    """本地 OCR 引擎是否可用（装没装 / 加载成败）。"""
    try:
        return _get_engine() is not None
    except Exception:
        return False