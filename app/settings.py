"""配置 + .env 读写。API key 只存 app/.env，接口只回尾 4 位掩码。

模型通道可配置（用户选择的：多渠道可配置）：
  LLM_PROVIDER = anthropic | openai   —— 接口协议
  LLM_BASE_URL                        —— 兼容接口地址（留空用官方默认）
  LLM_MODEL                           —— 模型名
  LLM_API_KEY                         —— 通道的 key
旧键 ANTHROPIC_API_KEY 作为 Anthropic 通道的默认 key 保留兼容。
"""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent          # D:\oneone\app
ROOT = APP_DIR.parent                              # D:\oneone
ENV_FILE = APP_DIR / ".env"

DEFAULT_MODEL = {    # 各协议默认模型（base_url 留空时用官方）
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o-mini",
}
DEFAULT_BASE_URL = { # None = 走官方 SDK 默认地址
    "anthropic": None,
    "openai": None,
}
MAX_TURN_TOKENS = 64000


def read_env() -> dict:
    vals = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    return vals


def _env_or(key: str, default=None):
    v = read_env().get(key)
    return v if v is not None and v != "" else default


def get_provider() -> str:
    p = (_env_or("LLM_PROVIDER") or "").lower()
    return p if p in ("anthropic", "openai") else "anthropic"


def get_model() -> str:
    return _env_or("LLM_MODEL", DEFAULT_MODEL[get_provider()])


def get_base_url() -> str | None:
    # 存了就用，空串视为默认官方地址
    raw = read_env().get("LLM_BASE_URL")
    return raw if raw and raw.strip() else DEFAULT_BASE_URL[get_provider()]


def get_api_key() -> str | None:
    # 通道 key 优先；Anthropic 兼容通道回退到旧键 ANTHROPIC_API_KEY
    key = read_env().get("LLM_API_KEY")
    if key:
        return key
    if get_provider() == "anthropic":
        return read_env().get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    return os.environ.get("LLM_API_KEY")


# ── 图片识别（识图）配置 ──────────────────────────────────────
# VISION_MODE: off 关闭 / ocr 只本地 / vision 只多模态 / auto 先OCR后视觉
# 通道默认复用主通道（provider/key/base_url），这三个键是「可选覆盖」：
#   VISION_MODEL     —— 覆盖视觉模型名（主通道是文本模型时可单独指 qwen-vl 等）
#   VISION_BASE_URL  —— 覆盖视觉接口地址
#   VISION_API_KEY   —— 覆盖视觉 key


def get_vision_mode() -> str:
    m = (_env_or("VISION_MODE") or "auto").lower()
    return m if m in ("auto", "ocr", "vision", "off") else "auto"


def get_vision_model() -> str:
    return _env_or("VISION_MODEL", get_model())


def get_vision_base_url() -> str | None:
    raw = _env_or("VISION_BASE_URL", None)
    if raw:
        return raw
    return get_base_url()


def get_vision_api_key() -> str | None:
    return _env_or("VISION_API_KEY", None) or get_api_key()


def masked_vision_key() -> str | None:
    key = get_vision_api_key()
    return f"…{key[-4:]}" if key and len(key) >= 8 else None


def masked_key() -> str | None:
    key = get_api_key()
    return f"…{key[-4:]}" if key and len(key) >= 8 else None


def save_settings(cfg: dict) -> dict:
    """把前端传的整份配置写进 .env。只认白名单键。
    api_key 空串 = 不改（避免前端留空把已存 key 冲掉）；
    其它字段空串 = 清空该项。base_url 空串表示用官方默认。
    """
    vals = read_env()
    allowed = {
        "provider": "LLM_PROVIDER",
        "base_url": "LLM_BASE_URL",
        "model": "LLM_MODEL",
        "api_key": "LLM_API_KEY",
        # 图片识别
        "vision_mode": "VISION_MODE",
        "vision_model": "VISION_MODEL",
        "vision_base_url": "VISION_BASE_URL",
        "vision_api_key": "VISION_API_KEY",
    }
    for cfg_key, env_key in allowed.items():
        if cfg_key not in cfg:
            continue
        v = cfg.get(cfg_key)
        if v is None:
            continue
        if env_key.endswith("API_KEY") and not (str(v).strip()):
            continue                     # key 留空不改，别冲掉
        vals[env_key] = str(v).strip() if v else ""
    ENV_FILE.write_text(
        "\n".join(f"{k}={v}" for k, v in vals.items()) + "\n", encoding="utf-8"
    )
    return current_settings()


def current_settings() -> dict:
    return {
        "provider": get_provider(),
        "base_url": get_base_url() or "",
        "model": get_model(),
        "masked_key": masked_key(),
        # 图片识别
        "vision_mode": get_vision_mode(),
        "vision_model": get_vision_model(),
        "vision_base_url": get_vision_base_url() or "",
        "masked_vision_key": masked_vision_key(),
    }