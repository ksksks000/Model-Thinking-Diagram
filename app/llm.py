"""统一 LLM 调用层：支持 Anthropic 兼容 / OpenAI 兼容两种协议。

converter 不直接碰 SDK，只调 complete()——管它后面是什么模型/中间商。
按 .env 里的 LLM_PROVIDER 分流：
  anthropic → anthropic SDK（base_url 留空走官方，填了就接中转商）
  openai    → openai SDK（同理，deepseek 等 OpenAI 兼容市场都吃这套）
"""
import base64
import re

from .settings import (
    get_api_key,
    get_base_url,
    get_model,
    get_provider,
    get_vision_api_key,
    get_vision_base_url,
    get_vision_model,
)


class LLMError(RuntimeError):
    pass


def strip_code_fence(text: str) -> str:
    """把模型可能裹的 ```md 围栏剥掉。两种协议产出一致处理。"""
    return re.sub(r"^```(?:md|markdown)?\n|\n```\s*$", "", text.strip())


def _anthropic_complete(system: str, user: str, max_tokens: int) -> str:
    """走 Anthropic 兼容协议。用流式——deepseek 的 /anthropic 端点要求
    max_tokens 较大时必须 streaming；官方 Claude 也支持流式，两边通吃。
    text_stream 只吐正文增量，自动跳过 thinking 块。"""
    import anthropic

    key = get_api_key()
    if not key:
        raise LLMError("没配 API key。去右上角「⚙ 设置」（通道 key）填。")
    kwargs = {"api_key": key}
    base = get_base_url()
    if base:
        kwargs["base_url"] = base
    client = anthropic.Anthropic(**kwargs)
    chunks = []
    with client.messages.stream(
        model=get_model(),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for piece in stream.text_stream:
            chunks.append(piece)
    return "".join(chunks)


def _openai_complete(system: str, user: str, max_tokens: int) -> str:
    from openai import OpenAI

    key = get_api_key()
    if not key:
        raise LLMError("没配 API key。去右上角「⚙ 设置」（通道 key）填。")
    kwargs = {"api_key": key}
    base = get_base_url()
    if base:
        kwargs["base_url"] = base
    client = OpenAI(**kwargs)
    resp = client.chat.completions.create(
        model=get_model(),
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    content = resp.choices[0].message.content if resp.choices else ""
    return content or ""


def _explain_error(exc: Exception) -> str:
    """把 SDK/网络异常翻译成用户一眼能懂的中文诊断。

    按「状态码 + 错误文本」双管齐下归类，因为不同 SDK（anthropic / openai）
    报错文本格式不同，只靠一种不保险。返回多行：结论 + 可能原因 + 处置。
    """
    status = getattr(exc, "status_code", None)
    # 有些 SDK 把 status 放在 body 里（第三方 Anthropic 兼容常有）
    if status is None:
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            status = body.get("status") or body.get("status_code")
    msg = (str(exc) or "").lower()

    # 1) 没抓到状态码 → 网络/连接/超时类
    if status is None:
        if "timeout" in msg or "timed out" in msg:
            return "请求超时——接口响应太慢或断了。\n处置：重试一次；还不行多半是网络/中转方的问题。"
        if "connection" in msg or "could not" in msg or "resolve" in msg or "unreachable" in msg:
            return "连不上接口地址——多半是「接口地址/端口对不上」或断网。\n处置：核对 ⚙ 设置里的接口地址（带不带 /v1 之类、协议对不对）。"
        if "ssl" in msg or "certificate" in msg:
            return "SSL/证书校验失败——接口地址可能写错，或对方只支持 http 你却填了 https。"
        return f"调用前就失败了（没拿到接口返回）：\n{str(exc)[:200]}"

    # 2) 按状态码归类
    if status in (401, 403):
        return ("KEY 无效/没权限（401/403）。\n"
                "可能：① key 填错或过期 ② key 是别家平台的、跟当前「接口类型+地址」不匹配\n"
                "处置：确认 key 来自你填的这个接口地址对应的平台。")
    if status == 402:
        return "账户欠费或未开通（402）。\n处置：去该平台控制台充值/开通模型权限。"
    if status == 404:
        return ("接口地址/路径不存在（404）——很可能是「接口类型」和「地址」不配套。\n"
                "例：选了 OpenAI 兼容却又填了 ……/anthropic 结尾的地址（那是 Anthropic 协议的接口），\n"
                "路径拼不到一块就 404。\n"
                "处置：对照供应商文档，把「接口类型 + 地址 + 模型名」三者配成一套。")
    if status == 429:
        return "请求太频繁或被限流（429）。\n处置：等几秒重试一次；常在高峰期出现的话换个时段。"
    if status == 400:
        if "model" in msg and ("not exist" in msg or "not found" in msg or "unknown" in msg):
            return ("模型名不对（model not found）。\n"
                    "你填的模型 id 在「这个接口地址」上不存在。\n"
                    "处置：查供应商文档的准确模型名（如 deepseek-chat / deepseek-v4-flash 等形式）。")
        if "max_tokens" in msg or "max output" in msg:
            return ("输出上限（max_tokens）设置不合适。\n"
                    "这个模型的实际最大输出比我设的 64000 小，或超出了。\n"
                    "处置：告诉我，我把值的上限按这个模型调小。")
        if "context" in msg or "input" in msg and ("too long" in msg or "exceed" in msg or "length" in msg):
            return ("输入超过模型的上下文窗口。\n"
                    "这份 PDF 的文字太长，超出了这个模型能吃下的量。\n"
                    "处置：换上下文更大的模型，或我把它拆更碎。")
        if "content" in msg and ("policy" in msg or "filter" in msg or "flag" in msg):
            return "内容被该平台的安全/内容策略拦下（400）。\n处置：这页可能触发了敏感词，换一段别的 PDF 试试确认是不是内容问题。"
        return f"接口说请求不合法（400）：\n{str(exc)[:250]}"

    if status in (500, 502, 503):
        return f"供应商服务器出错（{status}）。\n处置：过一会儿重试；持续出现是他们平台的问题。"
    if status == 529:
        return "供应商过载（529，就像 Claude 的负载保护）。\n处置：几分钟后再试。"

    return f"接口返回异常（HTTP {status}）：\n{str(exc)[:250]}"


def complete(system: str, user: str, max_tokens: int) -> str:
    """统一入口：按当前 provider 分流。空结果一律当作模型前端拦了。"""
    provider = get_provider()
    try:
        if provider == "openai":
            text = _openai_complete(system, user, max_tokens)
        else:
            text = _anthropic_complete(system, user, max_tokens)
    except LLMError:
        raise
    except Exception as exc:                      # SDK/网络错误 → 中文诊断
        diag = _explain_error(exc)
        current = (
            f"当前通道：{get_provider()} · 地址：{get_base_url() or '官方默认'} · 模型：{get_model()}"
        )
        raise LLMError(f"{diag}\n\n{current}") from exc
    if not text.strip():
        raise LLMError(
            "AI 返回了空内容。\n"
            "可能：① 这个模型输出上限太小，思考吃光了额度没轮到正文 ② 模型本身不擅长长文整理。\n"
            "处置：换输出更大的模型；实在不行换通道。"
        )
    return strip_code_fence(text)


def channel_label() -> str:
    """给进度提示用的友好名。"""
    return get_model()


# ── 图片识别（视觉模型识图） ──────────────────────────────────
# 通道默认复用主通道协议（provider），模型/地址/key 走视觉覆盖键
# （VISION_MODEL / VISION_BASE_URL / VISION_API_KEY），不覆盖则回落主通道。
# 调用失败由调用方回退本地 OCR，这里不吞异常（错误信息要透出）。


def vision_available() -> bool:
    """是否能发起视觉调用：有 key 且（主通道协议支持的）视觉模型名非空。"""
    return bool(get_vision_api_key())


def _vision_b64(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("ascii")


def _anthropic_vision(system: str, text: str, images: list[bytes], max_tokens: int) -> str:
    import anthropic

    key = get_vision_api_key()
    if not key:
        raise LLMError("没配 API key。去右上角「⚙ 设置」（通道 key）填。")
    kwargs = {"api_key": key}
    base = get_vision_base_url()
    if base:
        kwargs["base_url"] = base
    client = anthropic.Anthropic(**kwargs)

    content: list = []
    for b in images:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": _vision_b64(b)},
        })
    content.append({"type": "text", "text": text})

    chunks = []
    with client.messages.stream(
        model=get_vision_model(),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    ) as stream:
        for piece in stream.text_stream:
            chunks.append(piece)
    return "".join(chunks)


def _openai_vision(system: str, text: str, images: list[bytes], max_tokens: int) -> str:
    from openai import OpenAI

    key = get_vision_api_key()
    if not key:
        raise LLMError("没配 API key。去右上角「⚙ 设置」（通道 key）填。")
    kwargs = {"api_key": key}
    base = get_vision_base_url()
    if base:
        kwargs["base_url"] = base
    client = OpenAI(**kwargs)

    content: list = [{"type": "text", "text": text}]
    content += [
        {"type": "image_url", "image_url": {
            "url": f"data:image/png;base64,{_vision_b64(b)}"}}
        for b in images
    ]

    resp = client.chat.completions.create(
        model=get_vision_model(),
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
    )
    return (resp.choices[0].message.content if resp.choices else "") or ""


def complete_vision(system: str, text: str, images: list[bytes], max_tokens: int) -> str:
    """把一页的图 + 提示词发给视觉模型，返回识别文字。

    两张图以上一次调用塞进去（按页一次成一块的识别文本，便于编排）。
    错误不吞——抛 LLMError，由 vision 层决定是否回退本地 OCR。
    """
    provider = get_provider()
    try:
        if provider == "openai":
            return strip_code_fence(_openai_vision(system, text, images, max_tokens))
        return strip_code_fence(_anthropic_vision(system, text, images, max_tokens))
    except LLMError:
        raise
    except Exception as exc:
        diag = _explain_error(exc)
        current = (
            f"视觉通道：{get_provider()} · 模型：{get_vision_model()} · "
            f"地址：{get_vision_base_url() or '主通道默认'}"
        )
        raise LLMError(f"{diag}\n\n{current}") from exc