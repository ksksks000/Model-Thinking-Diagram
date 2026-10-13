# OneNote PDF → 思维导图

把 PDF 变成浏览器里可交互的思维导图——**全程不出浏览器**，不用碰命令行。

后端用 FastAPI 把 PDF 的文字层抽出来，交给大模型按固定规范整理成 Markmap 语法的 Markdown，
前端用 markmap 渲染成可缩放、可展开、可实时编辑的思维导图，并保留多份笔记的版本与清单。

> 定位：单人 / 单机的本地工具。不建数据库、不做鉴权、不联网存储，所有笔记以纯 Markdown 落在本地 `notes/` 目录。

---

## 目录

- [快速开始](#快速开始)
- [使用方法](#使用方法)
- [系统架构](#系统架构)
- [数据模型](#数据模型)
- [配置项](#配置项)
- [关键设计](#关键设计)
- [已知边界](#已知边界)

---

## 快速开始

### 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows（启动脚本为 `.bat`；核心逻辑跨平台，Linux/macOS 手动起服务即可） |
| Python | **3.10+**（代码使用了 `X \| None`、`list[str]` 等新语法） |
| 网络 | 首次装依赖需要；转换时需要能访问所配的大模型接口 |
| 浏览器 | 任一现代浏览器（Chrome / Edge / Firefox） |

### 一键启动

1. **双击 `启动.bat`**
   - 首次运行会自动创建虚拟环境 `venv/` 并安装依赖（约 1–2 分钟）；
   - 之后弹出服务窗口，并自动打开浏览器到 `http://localhost:8000/`。
2. **关闭那个黑窗口即停止服务。**

### 手动启动（任意平台）

```bash
python -m venv venv
venv\Scripts\python -m pip install -r app\requirements.txt   # Windows
# source venv/bin/activate && pip install -r app/requirements.txt   # Linux/macOS

venv\Scripts\python -m uvicorn app.main:app --port 8000
```

然后浏览器访问 `http://localhost:8000/`。

> ⚠️ **不能直接双击 `思维导图展示页面.html`**。页面通过 `fetch` 读取 `notes/` 下的文件，
> `file://` 协议会被浏览器 CORS 拦截，必须经由本地服务打开。

---

## 使用方法

### 1. 配置大模型通道

点工具栏 **⚙ 设置**，填入通道信息：

| 字段 | 说明 |
|---|---|
| 接口类型 | `Anthropic 兼容` 或 `OpenAI 兼容`，决定用哪套 SDK 协议 |
| 接口地址 | 兼容中转地址；留空则走官方默认（如直连 Claude / OpenAI） |
| 模型名 | 该通道上的模型 id（如 `claude-sonnet-4-5`、`deepseek-chat`） |
| API Key | 该通道的密钥 |

- 配置写入本机 `app/.env`，**不入库、不上传**；接口回显时只返回**尾 4 位掩码**。
- API Key 留空提交表示"不改动"，避免前端留空把已存的 key 冲掉。
- 支持**多渠道**：`Anthropic 兼容` / `OpenAI 兼容` 两种协议，中转商、国内模型市场（DeepSeek 等）都能接。

### 2. 转换 PDF

1. 点工具栏 **＋ 转换**；
2. 把 OneNote 导出的 PDF **拖进**面板，或点选文件；
3. 选风格：
   - **A · 原话派** —— 保留原文口吻、口语、比喻和自问自答，适合自己复习（层级最深 6 空格）；
   - **B · 纲要派** —— 压成"名词 + 括号注解"的短条目，适合快速速览（层级最深 4 空格）；
4. 点开始。面板会实时显示进度：**体检 → 抽文字 → 识图 → AI 整理（分批）→ 落盘登记**；
5. 完成后自动出现在左上角 **☰** 列表里，并在导图区渲染。

### 3. 管理导图

- **☰ 列表**：切换笔记；鼠标悬停条目右侧的 **⋯** 菜单可**重命名**、**设为默认**、**删除**。
- **✎ 编辑导图**：左侧开编辑面板、右侧导图实时保留的分屏模式。保存后只刷新内容、不关面板。
  编辑直接写回 `notes/<file>.md`（Markdown 是唯一真实来源）。
- **适配 / 展开 / 收起**：导图视图控制。
- **查看端口 PID**：排查 `8000` 端口被谁占用（走 `netstat` + PowerShell 拿进程名与命令行）。

### 4. 图片识别（可选）

OneNote 里的**截图 / 手写 / 图表**不属于文字层，默认不参与整理。开启后会把页面图片识别成文字，
并回填进原文再交给模型。模式：

| 模式 | 行为 | 费用 |
|---|---|---|
| `off` | 不识别 | 无 |
| `ocr` | 只用本地 RapidOCR（离线） | 免费 |
| `vision` | 只用多模态视觉模型 | 按量计费 |
| `auto`（默认） | 先本地 OCR；结果过短（疑手写/图表/代码）才调视觉模型 | 视情况 |

---

## 系统架构

### 总览

```
┌──────────────────────────────────────────────────────────────────┐
│  浏览器（前端，纯静态）                                            │
│                                                                    │
│   index.html ──(meta refresh)──▶ 思维导图展示页面.html              │
│                                     │  ├─ markmap 渲染（esm.sh CDN） │
│                                     │  └─ window.mindmap 反查 API    │
│   convert-ui.js ─── 转换 / 设置 / 编辑 / 端口 面板 ──▶ window.mindmap │
│   convert-ui.css                                                   │
└───────────────────────────────┬──────────────────────────────────┘
                    fetch / SSE  │  /api/*（同源，无跨域）
┌───────────────────────────────▼──────────────────────────────────┐
│  FastAPI 后端（app/，单进程）                                       │
│                                                                    │
│   HTTP 层      main.py     ── 路由 / 静态挂载 / 全静态 no-store      │
│   编排层       converter.py ── 转换管线：体检→抽字→识图→整理→登记    │
│   能力层   checker / images / ocr / vision / llm / prompts/*        │
│   底座      settings（配置读写）· jobs（内存任务表 + SSE 进度）      │
└───────────────────────────────┬──────────────────────────────────┘
                                │
              大模型接口（Anthropic / OpenAI 兼容）
                                │
┌───────────────────────────────▼──────────────────────────────────┐
│  本地存储                                                          │
│   notes/index.json   笔记清单（版本登记）                          │
│   notes/<name>.md     每份导图的 Markdown 正文（唯一真实来源）      │
│   app/.env           通道配置（含 key，不入库）                     │
│   app/temps/         上传的 PDF 与中间产物（转换后清理）            │
└──────────────────────────────────────────────────────────────────┘
```

### 目录结构

```
.
├─ 启动.bat                    一键启动：建 venv → 装依赖 → 起 uvicorn → 开浏览器
├─ index.html                  入口页，meta refresh 跳到展示页（避开中文文件名转义）
├─ 思维导图展示页面.html        markmap 渲染页（渲染 / 连线 / 交互 / 列表 / 工具栏）
├─ convert-ui.js               转换面板等增量 UI，经 window.mindmap 与渲染页通信
├─ convert-ui.css              转换面板样式
├─ app/                        FastAPI 后端
│  ├─ main.py                  API 路由 + 静态挂载 + no-cache 中间件
│  ├─ converter.py             转换管线编排 + 版本命名 + index.json 登记
│  ├─ checker.py               PDF 体检（三档分类）+ 逐页抽文字层
│  ├─ images.py                从 PDF 提取待识别图片（整页渲染 / 内嵌位图）
│  ├─ ocr.py                   本地 RapidOCR 封装（懒加载单例）
│  ├─ vision.py                识图编排：按模式在本地 OCR 与视觉模型间选择/回退
│  ├─ llm.py                   统一 LLM 调用层（双协议）+ 错误中文诊断
│  ├─ settings.py              .env 读写 / key 掩码 / 视觉配置
│  ├─ jobs.py                  内存任务表 + 进度事件
│  ├─ prompts/                 整理规范与风格片段
│  │  ├─ spec.md               通用整理规范
│  │  ├─ style_a.md / style_b.md   两种风格的片段
│  │  ├─ samples/              风格样例锚（脱敏，供 few-shot 对齐密度）
│  │  ├─ system_prompt.py      组装 system prompt（规范 + 风格 + 样例锚）
│  │  └─ vision_ocr.py         视觉模型用的 OCR 提示词
│  ├─ requirements.txt         依赖清单
│  ├─ .env.example             配置模板（复制为 .env 使用）
│  └─ temps/                   上传的 PDF 临时目录（运行时生成）
└─ notes/                      笔记产出目录（运行时生成）
   ├─ index.json               清单
   └─ <name>-<YYYYMMDD>.md     各份导图
```

### 后端模块

#### `main.py` — HTTP 层

静态挂载**项目根目录**（`StaticFiles`），把所有 `app/` 源码目录也一并挂出去，
好处是 `notes/` 的相对路径在前端保持不变、渲染页零改动即可用。路由：

| 方法 & 路径 | 作用 |
|---|---|
| `POST /api/convert?style=` | 接收 PDF 上传 → 存 `temps/` → 建任务 → 起后台线程 |
| `GET /api/jobs/{id}/events` | **SSE** 流式推送转换进度（只推有变化的帧） |
| `GET` / `POST /api/settings` | 读配置 / 存配置（key 可留空表示不改） |
| `PUT /api/notes/{id}/content` | 编辑保存：把正文写回 `notes/<file>.md` |
| `PATCH /api/notes/{id}` | 重命名 / 设默认 |
| `DELETE /api/notes/{id}` | 删除（只删清单登记过的文件） |
| `GET /api/port/{port}` | 查端口占用进程（netstat + PowerShell） |

一个**全局中间件**给所有静态资源加 `Cache-Control: no-store`——
改前端文件后刷新即生效，不必靠 `?v=` 或强制刷新。

#### `converter.py` — 编排层

转换管线的主体，在**后台线程**里跑，进度经 `jobs` 上报。核心步骤：

```
PDF ──▶ check()          体检查页 ─┐
     ──▶ extract_pages() 抽文字层  │ 组装带 ===== PAGE N ===== 标记的原文 raw
     ──▶ images/vision   识图回填 ─┘
     ──▶ split_batches()  长文分批（每批约 3 万字符）
     ──▶ llm.complete()   逐批整理（延续同一风格）
     ──▶ validate()       机械校验（缩进/结构）
     ──▶ finalize_note()  命名落盘 + 登记 index.json
     ──▶ 清理 temps
```

- **分批**：按 `===== PAGE N =====` 切批而非按标题（PDF 文字层本就没有 md 标题），
  尽量凑满每批以减少批数与文风漂移；非首批带"延续上一批风格、接上断句"的前缀。
- **版本命名**：`notes/<base>-<YYYYMMDD>.md`；同日第二版起补时分（早的那份也一并改名，避免一半带一半不带）。
- **并发一致性**：`with_index_lock` = 进程内 `threading.Lock` + 跨进程 `portalocker` 文件锁，
  写 `index.json` 走**临时文件 + 原子 replace**，防"连发两单"同时写。

#### `checker.py` — 体检 + 抽字

- `check()`：用 **pypdf** 逐页数有效字数（剥掉页脚「…的第 N 页」和时间戳后），分三档：
  - `rich`（> 40 字，正文可用）、`labeled`（1–40 字，像页面标题）、`blank`（0 字，内容全在图里）。
- `extract_pages()`：用 **pdfplumber** 逐页抽文字层。
  **不用 `pdftotext`**——OneNote 文本框顺序不保证，`pdftotext` 会串行，pdfplumber 按坐标更稳。

#### `images.py` + `ocr.py` + `vision.py` — 识图

- `images.candidates()`：blank 页 → **整页渲染**（`get_pixmap`，连带兜住矢量元素）；
  有正文的页 → 只取**内嵌位图**（保留原像素、体积小，且不会重复识别已有文字层）。
  按"够大"过滤小图标，按 `xref` 去重（同一张图被多页复用只取一次）。
- `ocr.recognize()`：**RapidOCR（ONNX）** 懒加载单例，首次加载模型约 18s，之后进程内复用；
  任何异常内部消化、返回空串，绝不因单张图拖垮整个任务。
- `vision.recognize_page()`：按 `VISION_MODE` 编排并在失败时**回退**——
  视觉通道没配/无效 → 退回本地 OCR；两者都失败 → 返回可见的失败标记（不静默丢图）。
- 识图是**增强**，任何失败只 `pass`，绝不中断主流程。

#### `llm.py` — 统一调用层

`converter` 不直接碰 SDK，只调 `complete()` / `complete_vision()`。按 `.env` 的 `LLM_PROVIDER` 分流：

- `anthropic` → `anthropic` SDK；`openai` → `openai` SDK。`base_url` 留空走官方，填了就接中转。
- **流式**：Anthropic 通道统一用 `messages.stream`——DeepSeek 的 `/anthropic` 端点在大 `max_tokens` 下**要求流式**，
  官方 Claude 也支持，两边通吃。
- **错误诊断**：按「状态码 + 错误文本」双管齐下分类，把 SDK/网络异常翻译成中文处置建议
  （401/403 key 问题、404 协议与地址不配套、400 模型名错、429 限流、5xx 供应商故障……）。

#### `settings.py` — 配置底座

`.env` 的读写与掩码。只认**白名单键**；写回时 key 留空视为"不改"。对外只暴露**尾 4 位掩码**。

#### `jobs.py` — 任务与进度

进程内内存表，**不建库、不落盘**（单机单用户）。任务经 `update()` 上报阶段/百分比/消息，
SSE 端点轮询 `snapshot()` 推增量帧；`finish()` 用 `Event` 收尾。

### 前端

#### `思维导图展示页面.html` — 渲染页

一个 ES module（自 `esm.sh` 动态 `import` `markmap-view` / `markmap-lib`），模块划分：
配置 → 内容加载 → 工具栏 → 渲染 → 连线 → 节点圆心 → 交互 → 启动。

- **多份导图共存**：每份导图 = 一个独立 `<svg class="mm-canvas">` + 一个独立 markmap 实例，
  各自记住展开层级与缩放；首屏只渲染第一份，其余首次切过去才懒创建。
- **内容来自文件**：`fetch('notes/index.json')` + 各 `.md` 正文。加一份导图 = 加一个 `.md` + 清单加一行，**不动渲染页代码**。
- **宣纸黄 + 墨黑 + 朱砂红**配色；连线按层级上色、新生曲线带"生长"动画。
- 对外暴露 `window.mindmap`（`activate` / `fit` / `setExpandLevel` / `reloadIndex`），供增量 UI 反查调用。

#### `convert-ui.js` — 增量 UI

独立于渲染代码，经 `window.mindmap` 通信；图标按钮写死在 HTML 里，本文件只**挂事件**（避免"脚本时序导致按钮不出现"）。
负责：**⚙ 设置面板**、**＋ 转换面板**（拖拽/点选上传、SSE 进度、三档体检展示）、**✎ 编辑器**（分屏、带搜索、行号）、
**☰ 列表增强**（重命名/设默认/删除）、**端口 PID 面板**。仅在 `http(s)` 协议下启用。

---

## 数据模型

### `notes/index.json` — 笔记清单

```jsonc
{
  "trees": [
    {
      "id": "bagu-20260927-2150",          // 唯一 id，= 文件名去扩展名
      "title": "八股积累 09-27 21:50",      // 列表显示名（可改）
      "file": "notes/bagu-20260927-2150.md",
      "gaps": ["第 12 页：纯截图，未能转写"], // 可选：整理时发现的缺口
      "default": true                       // 可选：默认打开的那份（单选）
    }
  ]
}
```

### 笔记文件

- 命名：`notes/<base>-<YYYYMMDD>[-HHMM].md`，`<base>` 取自 PDF 文件名（清洗为 ASCII、小写、最长 40 字符）。
- 正文：纯 Markdown，**顶部一行 `# 标题`**，其余为列表构成的思维导图（Markmap 只渲染标题和列表）。
- **Markdown 是唯一真实来源**：编辑保存直接覆盖它，`index.json` 只登记元数据。

---

## 配置项

配置全部落在 `app/.env`（见 `app/.env.example`）：

| 键 | 含义 | 默认 |
|---|---|---|
| `LLM_PROVIDER` | 协议：`anthropic` \| `openai` | `anthropic` |
| `LLM_BASE_URL` | 兼容接口地址（留空走官方） | 空（官方） |
| `LLM_MODEL` | 模型名 | 按协议取默认 |
| `LLM_API_KEY` | 通道密钥 | 空 |
| `ANTHROPIC_API_KEY` | 旧键，作 Anthropic 通道默认 key 兼容 | 空 |
| `VISION_MODE` | 识图模式：`off` \| `ocr` \| `vision` \| `auto` | `auto` |
| `VISION_MODEL` | 覆盖视觉模型名（不填复用主通道） | 主通道模型 |
| `VISION_BASE_URL` | 覆盖视觉接口地址 | 主通道地址 |
| `VISION_API_KEY` | 覆盖视觉密钥 | 主通道 key |

---

## 关键设计

- **浏览器即界面**：前端零构建、纯静态，后端只做"取文字 + 调模型 + 落盘"，学习成本最低。
- **Markdown 为唯一真实来源**：笔记以纯文本存于 `notes/`，编辑即改文件，随时可被别的工具消费。
- **版本不覆盖**：同日多版自动补时分后缀名，旧版永不丢。
- **写清单强一致**：文件锁 + 原子替换，容忍"连发两单"。
- **失败必须可见**：识图失败留标记而非静默丢；转换失败也一定发 `done/error` 终态帧。
- **错误是为人写的**：把 SDK/网络错误翻译成"结论 + 可能原因 + 处置"的中文诊断。
- **双协议解耦**：模型通道可换，`converter` 与具体 SDK 无关。

---

## 已知边界

- 纯截图页**无文字层**，只能靠上下文推断或留缺口——需要识图请开启视觉模式。
- 图片本身不入导图；代码截图**不进 md**（导图要的是骨架，不是代码仓库）。
- `max_tokens` 上限（`app/settings.py` 的 `MAX_TURN_TOKENS`）可能与该模型实际输出上限不符，
  超长 PDF 若被截断，需按模型调小。
- 单机单用户设计：无鉴权、无数据库、任务表在内存（重启即清空）。
