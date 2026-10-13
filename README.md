# OneNote PDF → 思维导图

把 OneNote 导出的 PDF 变成浏览器里的思维导图——全程不出浏览器，不用碰终端。

## 怎么用

1. **双击 `启动.bat`**：第一次会自动装依赖（1-2 分钟），然后弹黑窗口 + 自动开浏览器
2. **左上角点 ⚙ 设置**：填入你的 Claude API Key（只存本机 `app/.env`，每条转换按量计费，很便宜）
3. **点「＋ 转换」**：把 PDF 拖进去 → 选风格 → 开始
   - **A · 原话派**：保留你的原话和口语，适合自己复习
   - **B · 纲要派**：压成短条目，适合速览
4. 转完点左上 **☰**，列表里就有新笔记

## 找我修问题

| 问题 | 找哪 |
|---|---|
| 转换失败 | 页面上有红色报错，直接抄给 Claude |
| API 余额/费用 | console.anthropic.com 查 |
| 想改整理规范 | `app/prompts/spec.md`（通用）+ `style_a.md` / `style_b.md` |
| 服务起不来 | 黑窗口里的报错 |

## 是什么在跑

```
浏览器（思维导图展示页面.html + convert-ui.js 转换面板）
   │
FastAPI 后端（app/）
   ├─ pypdf 体检       ← 每页数字数分三档，纯截图页留缺口
   ├─ pdfplumber 抽字   ← 按 OneNote 文本框坐标抽，行序不乱
   ├─ Claude API 整理   ← 规范在 app/prompts/，模型 claude-sonnet-4-5
   └─ 登记进 notes/index.json（绝不覆盖旧版，文件名带日期时间）
```

同目录另一套「终端 + Claude CLI」的手动兜底流程在 `D:\onenote导出`（老文件夹，没动）。
