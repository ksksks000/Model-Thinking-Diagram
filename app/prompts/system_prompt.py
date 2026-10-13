"""system_prompt 组装：spec.md + 风格片段 + 对应参考样例首 30 行。

参考样例就是对齐密度的锚，随包放在 prompts/samples/（脱敏，可入库）。
要改规范去改 prompts/*.md，别在这里复述文案。
"""
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent

SAMPLES = {
    "A": PROMPTS_DIR / "samples" / "sample_a.md",
    "B": PROMPTS_DIR / "samples" / "sample_b.md",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sample_head(style: str, lines: int = 30) -> str:
    sample = SAMPLES.get(style)
    if not sample or not sample.exists():
        return "（暂无参考样例）"
    head = sample.read_text(encoding="utf-8").splitlines()[:lines]
    return "\n".join(head)


def build_system_prompt(style: str) -> str:
    style = style.upper()
    spec = _read(PROMPTS_DIR / "spec.md")
    style_file = PROMPTS_DIR / ("style_a.md" if style == "A" else "style_b.md")
    style_md = _read(style_file).replace(
        "{SAMPLE_HEAD}", _sample_head(style)
    )
    return (
        spec
        + "\n\n"
        + style_md
        + "\n\n---\n\n"
        + "只输出整理后的 Markdown 笔记本身，不要任何解释、寒暄或代码围栏。"
    )
