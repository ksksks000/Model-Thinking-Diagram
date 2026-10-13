"""FastAPI 入口：静态挂载 D:/oneone + 转换/进度/设置/版本管理 API。

静态文件挂根目录，notes\ 的 fetch 路径不变，渲染页零改动可用。
"""
import asyncio
import json
import re
import subprocess
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import converter, jobs, settings
from .settings import ROOT

app = FastAPI()

TEMP_DIR = settings.APP_DIR / "temps"
TEMP_DIR.mkdir(exist_ok=True)
NOTES_DIR = ROOT / "notes"
INDEX_FILE = NOTES_DIR / "index.json"

ALLOWED_SUFFIX = ".pdf"


# ── 转换 ─────────────────────────────────────────────────────────


@app.post("/api/convert")
async def convert(pdf: UploadFile, style: str = "A"):
    if not pdf.filename or not pdf.filename.lower().endswith(ALLOWED_SUFFIX):
        raise HTTPException(400, "只收 PDF 文件")
    if style.upper() not in ("A", "B"):
        raise HTTPException(400, "style 只能是 A 或 B")

    dest = TEMP_DIR / Path(pdf.filename).name
    with open(dest, "wb") as fh:
        fh.write(await pdf.read())

    job = jobs.create(pdf.filename, style.upper())
    threading.Thread(target=converter.run, args=(job,), daemon=True).start()
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "没有这个任务")

    async def gen():
        last_full = None
        while True:
            snap = job.snapshot()
            payload = json.dumps(snap, ensure_ascii=False)
            if payload != last_full:            # 只推有变化的帧
                last_full = payload
                yield f"data: {payload}\n\n"
            if snap["phase"] in ("done", "error"):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── 设置（key 的掩码读写） ────────────────────────────────────────


@app.get("/api/settings")
async def get_settings():
    return settings.current_settings()


@app.post("/api/settings")
async def post_settings(body: dict):
    # 整份配置：接口类型 / base_url / model / api_key（api_key 可留空表示不改）
    return settings.save_settings(body)


# ── 版本管理（notes/index.json 的增改删） ─────────────────────────


def _load_index() -> dict:
    if not INDEX_FILE.exists():
        return {"trees": []}
    return json.loads(INDEX_FILE.read_text(encoding="utf-8"))


def _save_index(data: dict):
    tmp = INDEX_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(INDEX_FILE)


@app.delete("/api/notes/{note_id}")
async def delete_note(note_id: str):
    data = _load_index()
    trees = data.get("trees", [])
    hit = next((t for t in trees if t["id"] == note_id), None)
    if not hit:
        raise HTTPException(404, "清单里没有这条")

    md_file = ROOT / hit["file"]
    if md_file.exists():
        md_file.unlink()                          # 只有清单里登记过的才敢删文件
    data["trees"] = [t for t in trees if t["id"] != note_id]
    converter.with_index_lock(lambda: _save_index(data))
    return {"ok": True}


@app.put("/api/notes/{note_id}/content")
async def update_note_content(note_id: str, body: dict):
    """编辑保存：把页面里改好的 md 写回 notes\\<file>（唯一真实来源）。

    不动 index.json——编辑不改标题、不改归属，只覆盖正文。
    """
    md = body.get("content")
    if not isinstance(md, str) or not md.strip():
        raise HTTPException(400, "content 不能为空")
    if not md.lstrip().startswith("# "):
        raise HTTPException(400, "md 必须以 '# ' 开头的标题起手")

    data = _load_index()
    hit = next((t for t in data.get("trees", []) if t["id"] == note_id), None)
    if not hit:
        raise HTTPException(404, "清单里没有这条")

    md_file = ROOT / hit["file"]
    if not md_file.exists():
        raise HTTPException(404, f"文件不存在：{hit['file']}")

    md_file.write_text(md, encoding="utf-8")
    return {"ok": True, "id": note_id}


# ── 端口占用查询（供「查看端口 PID」面板） ──────────────────────


def _port_pids(port: int) -> list[int]:
    """netstat 找指定端口上 LISTENING 的进程 PID。"""
    r = subprocess.run(["netstat", "-ano"], capture_output=True)
    text = r.stdout.decode("ascii", errors="replace")
    port_str = str(port)
    pids = []
    for ln in text.splitlines():
        parts = ln.split()
        if len(parts) >= 4 and parts[0] == "TCP" and parts[3] == "LISTENING":
            local = parts[1]
            if local.rsplit(":", 1)[-1] == port_str and parts[-1].isdigit():
                pids.append(int(parts[-1]))
    return pids


def _proc_info(pid: int) -> dict | None:
    """拿进程名和命令行（用 PowerShell，比 wmic 稳）。"""
    try:
        r = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").Name",
            ],
            capture_output=True,
        )
        name = r.stdout.decode("gbk", errors="replace").strip()
        r = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
            ],
            capture_output=True,
        )
        cmd = r.stdout.decode("gbk", errors="replace").strip()
        return {"pid": pid, "name": name or "?",
                "command": cmd or f"(进程 {pid} 已退出)"}
    except Exception:
        return {"pid": pid, "name": "?", "command": f"(查询失败)"}


@app.get("/api/port/{port}")
async def port_check(port: int):
    if not (1 <= port <= 65535):
        raise HTTPException(400, "端口范围 1-65535")
    return {"port": port, "procs": [_proc_info(p) for p in _port_pids(port)]}


@app.patch("/api/notes/{note_id}")
async def patch_note(note_id: str, body: dict):
    data = _load_index()
    trees = data.get("trees", [])
    hit = next((t for t in trees if t["id"] == note_id), None)
    if not hit:
        raise HTTPException(404, "清单里没有这条")

    if "title" in body and body["title"].strip():
        hit["title"] = body["title"].strip()
    if body.get("make_default"):
        for t in trees:                            # 单选默认，别出现两个
            t["default"] = t["id"] == note_id
    elif "make_default" in body:
        hit.pop("default", None)
    converter.with_index_lock(lambda: _save_index(data))
    return {"ok": True}


# ── 静态文件（挂最后，/api 路由优先匹配） ─────────────────────────

# 静态资源一律 no-store：修改任何前端文件后浏览器刷新即生效，
# 不必靠 ?v= 或让用户 Ctrl+F5（曾经多次被浏览器旧缓存坑到）。
NO_CACHE_SUFFIXES = (
    ".html", ".htm", ".js", ".css", ".json", ".md",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico",
)


@app.middleware("http")
async def no_cache_for_static(request, call_next):
    response = await call_next(request)
    path = request.url.path.lower()
    if any(path.endswith(s) for s in NO_CACHE_SUFFIXES):
        response.headers["Cache-Control"] = "no-store"
    return response


app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="static")
