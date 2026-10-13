/* ═══════════════════════════════════════════════════════════
   转换面板 —— 独立于渲染代码的增量，经 window.mindmap 反查通信
   功能：⚙ 设置 key / 「＋ 转换」按拖拽或点选上传 PDF，
         体检三档展示，风格 A/B 单选，SSE 进度，完成后刷新列表

   图标按钮（＋ 转换 / ⚙ 设置）写死在 思维导图展示页面.html 的
   工具栏里，本文件只负责给它们挂事件 —— 不靠 JS 创建按钮，
   避免「脚本时序导致按钮不出现」的问题。
   ═══════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  /* 仅本地服务（http/https）下启用；file:// 下渲染页已有提示，这里不插手 */
  if (location.protocol !== 'http:' && location.protocol !== 'https:') return;

  var state = {
    pollTimer: null,     // 三档体检的轮询（等 SSE 连上就不用了）
    sse: null,
    toolItem: null,
  };

  /* ── 样式注入（古籍配色变量沿用渲染页的 :root）
     带版本号：样式文件被浏览器缓存过的话，可能看到旧配色/旧布局。 */
  var css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = 'convert-ui.css?v=20261010';
  document.head.appendChild(css);

  /* ── 给 HTML 里写死的工具栏按钮挂事件 ─────────────────── */
  function injectToolbar() {
    var conv = document.querySelector('[data-action="convert"]');
    if (conv) conv.addEventListener('click', function (e) { e.preventDefault(); openConverter(); });

    var gear = document.querySelector('[data-action="settings"]');
    if (gear) gear.addEventListener('click', function (e) { e.preventDefault(); openSettings(); });

    var port = document.querySelector('[data-action="portcheck"]');
    if (port) port.addEventListener('click', function (e) { e.preventDefault(); openPortCheck(); });

    var edit = document.querySelector('[data-action="edit"]');
    if (edit) edit.addEventListener('click', function (e) { e.preventDefault(); openEditor(); });
  }

  /* ── 编辑导图面板（改 md 原文 → 保存 → 重渲染） ─────────── */
  function openEditor() {
    var mm = window.mindmap;
    if (!mm || !mm.trees) return;
    // 已开着就只切换内容，不复建（保存后的 tree.md 是最新的）
    var panel = document.querySelector('.cu-editor-panel');
    if (panel) { fillEditor(panel, mm); panel.focus(); return; }

    var activeId = currentTreeId(mm);
    var tree = mm.trees.find(function (t) { return t.id === activeId; });
    if (!tree || !tree.md) return;

    var panel = document.createElement('div');
    panel.className = 'cu-editor-panel';
    var s = document.createElement('div');
    s.className = 'cu-editor-panel-inner';
    s.tabIndex = -1;
    s.innerHTML =
      '<div class="cu-panel-head">'
      + '  <h2>✎ 编辑导图</h2>'
      + '  <span class="cu-panel-title" id="cuEditorTitle"></span>'
      + '</div>'
      + '<div class="cu-search">'
      + '  <input id="cuSearch" type="text" class="cu-input" placeholder="搜索" autocomplete="off">'
      + '  <span id="cuSearchInfo"></span>'
      + '  <button class="cu-btn" id="cuSearchPrev" title="上一个（Shift+Enter）">↑</button>'
      + '  <button class="cu-btn" id="cuSearchNext" title="下一个（Enter）">↓</button>'
      + '</div>'
      + '<p class="cu-hint cu-tips">快捷键：'
      + '<b>Ctrl+F</b> 聚焦搜索 · <b>回车</b> 下一个 · <b>Shift+回车</b> 上一个 · <b>Esc</b> 返回正文。<br>'
      + '回车只负责「选中到下一处」；想改字，点击正文任意位置，光标落哪就改哪。</p>'
      + '<p class="cu-hint">正文是 Markdown，每次<b>保存并更新</b>只会刷新右侧导图、<b>不会关面板</b>——'
      + '改到满意为止，最后点<b>关闭</b>。<br>'
      + '缩进 <b>2 空格</b>（偶数），# 标题 · - 条目。</p>'
      + '<textarea id="cuEdit" spellcheck="false" class="cu-input cu-ta" wrap="off"></textarea>'
      + '<div class="cu-row cu-panel-foot">'
      + '  <button class="cu-btn cu-primary" id="cuSave">保存并更新</button>'
      + '  <button class="cu-btn" id="cuClose">关闭</button>'
      + '</div>';
    panel.appendChild(s);
    document.body.appendChild(panel);
    document.body.classList.add('cu-split');   // CSS 把导图推到右侧

    fillEditor(panel, mm);

    // 面板开着时，点 ☰ 切换导图 → 面板跟随刷新（懒绑定一次）
    var listEl = document.getElementById('treeList');
    if (listEl && !listEl.dataset.cuSync) {
      listEl.dataset.cuSync = '1';
      listEl.addEventListener('click', function () {
        var p = document.querySelector('.cu-editor-panel');
        if (p) setTimeout(function () { fillEditor(p, window.mindmap); }, 0);
      });
    }

    var ta = panel.querySelector('#cuEdit');
    panel.querySelector('#cuClose').addEventListener('click', function () { closeEditor(panel); });
    panel.querySelector('#cuSave').addEventListener('click', function () {
      var content = ta.value;
      if (!content.trim()) { alert('内容不能为空'); return; }
      fetch('/api/notes/' + activeId + '/content', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: content }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || '保存失败'); });
          return r.json();
        })
        .then(function () {
          mm.reloadActive(content);     // 右侧立即更新，面板留着
          flash('已保存，右侧已更新 ✓');
        })
        .catch(function (e) { alert('保存失败：' + e.message); });
    });
    ta.focus();
    setupEditorSearch(panel, ta);       // 搜索（Ctrl+F 聚焦搜索框）

    // 分屏后画布宽度变了，等面板布局稳定再重新 fit，否则右侧显示不完整
    setTimeout(function () {
      try { mm.fit(); } catch (err) {}
    }, 60);
  }

  function closeEditor(panel) {
    panel.remove();
    document.body.classList.remove('cu-split');
    // 回到整屏，画面重排一次
    setTimeout(function () {
      try { window.mindmap && window.mindmap.fit(); } catch (err) {}
    }, 60);
  }

  /** 当前正在看哪份（列表里的 .current 项） */
  function currentTreeId(mm) {
    var cur = document.querySelector('#treeList .tl-item.current');
    return cur ? cur.dataset.treeId : mm.trees[0].id;
  }

  /** 把面板填成当前导图的内容（初次打开 / 切换导图时用） */
  function fillEditor(panel, mm) {
    var title = panel.querySelector('#cuEditorTitle');
    var ta = panel.querySelector('#cuEdit');
    var activeId = currentTreeId(mm);
    var tree = mm.trees.find(function (t) { return t.id === activeId; });
    if (title) title.textContent = tree ? tree.title : '';
    if (ta) ta.value = tree ? tree.md : '';
  }

  /* ── 编辑器内搜索 ──
     行为约定（跟用户确认过的）：
     · 回车只负责「展示选中到下一处」，不进入编辑，也不改文本
     · 想编辑：点击正文任意位置 → 光标落哪就改哪（点一下即退出搜索态）
     · Enter 下一个 / Shift+Enter 上一个 / Ctrl+F 聚焦搜索 / Esc 返回正文   */
  function setupEditorSearch(box, ta) {
    var input = box.querySelector('#cuSearch');
    var info = box.querySelector('#cuSearchInfo');
    var prev = box.querySelector('#cuSearchPrev');
    var next = box.querySelector('#cuSearchNext');
    if (!input) return;

    var matches = [];       // 当前关键词所有 [start, end]
    var current = -1;       // 当前第几个（0-based）
    var lastQuery = '';     // 上一次搜的关键词
    var searching = false;  // 搜索态：true 时正文里的 Enter 也被接管为「下一个」，且点击正文才退出

    /* 收集当前关键词的所有出现位置 */
    function collect(q, text) {
      var arr = [], idx = 0;
      while (idx <= text.length - q.length) {
        var at = text.indexOf(q, idx);
        if (at === -1) break;
        arr.push([at, at + q.length]);
        idx = at + q.length;
      }
      return arr;
    }

    /* 定位：始终基于当前光标位置，不靠下标记忆——
       按下=光标后第一个；按上=光标前最后一个；边界环绕。
       这样无论点了正文、按过几次按钮，跳转永远跟用户看到的视角一致 */
    function step(forward) {
      var pos = ta.selectionStart;
      var hit = -1;
      if (forward) {
        for (var b = 0; b < matches.length; b++) {
          if (matches[b][0] > pos) { hit = b; break; }
        }
        if (hit === -1) hit = 0;              // 光标后没有了 → 环绕回第一个
      } else {
        for (var b2 = matches.length - 1; b2 >= 0; b2--) {
          if (matches[b2][0] < pos) { hit = b2; break; }
        }
        if (hit === -1) hit = matches.length - 1;  // 光标前没有了 → 环绕回最后一个
      }
      current = hit;
    }

    function doSearch(forward) {
      var q = input.value;
      if (!q) { info.textContent = ''; info.className = ''; return; }
      var text = ta.value;

      if (q !== lastQuery) {          // 关键词变了 → 重新收集，重新定位
        lastQuery = q;
        matches = collect(q, text);
        current = -1;
      }

      if (!matches.length) { info.textContent = '无匹配'; info.className = 'cu-err'; return; }
      info.className = '';

      step(forward);
      var pair = matches[current];
      showAt(ta, pair);
      var li = lineAt(text, pair[0]);
      info.textContent = (current + 1) + ' / ' + matches.length
        + ' · 第 ' + li.n + ' 行：' + li.preview;
    }

    /* 展示选中：聚焦正文让选区高亮可见（Enter 已被搜索态接管，
       不会误入编辑换行）；滚动命中行到可见区 */
    function showAt(ta, pair) {
      ta.focus();
      ta.setSelectionRange(pair[0], pair[1]);
      // 滚动按「命中行号占比」估——文本各行高低不均，
      // 用字符占比会把命中行滚到视野外（之前的就是这个 bug）
      if (ta.value.length && ta.clientHeight) {
        var text = ta.value;
        var nLine = lineNumberAt(text, pair[0]);
        var total = lineNumberAt(text, text.length);
        var ratio = total > 1 ? (nLine - 1) / (total - 1) : 0;
        ta.scrollTop = ratio * (ta.scrollHeight - ta.clientHeight);
      }
      searching = true;                // 进入「搜索态」：正文 Enter 被接管
    }

    /* 数 text[0, pos) 里有多少个换行 → pos 所在行号（1-based） */
    function lineNumberAt(text, pos) {
      var n = 1, idx = -1;
      while ((idx = text.indexOf('\n', idx + 1)) !== -1 && idx < pos) n++;
      return n;
    }

    /* 把字符偏移换算成「行号 + 该行内容」——选区可能看不清，行号总跑不掉 */
    function lineAt(text, pos) {
      var n = 1, lineStart = -1, idx = -1;
      while ((idx = text.indexOf('\n', idx + 1)) !== -1 && idx < pos) {
        n++;
        lineStart = idx;
      }
      var start = lineStart + 1;
      var end = text.indexOf('\n', start);
      if (end === -1) end = text.length;
      var preview = text.slice(start, end).trim();
      return { n: n, preview: preview.length ? preview : '(空行)' };
    }

    /* 搜索框交互 */
    next.addEventListener('click', function () { doSearch(true); });
    prev.addEventListener('click', function () { doSearch(false); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        doSearch(e.shiftKey ? false : true);
        // 注意：这里不能再 input.focus()——前一版就是它把焦点抢回搜索框，
        // 让 showAt 刚聚焦的 textarea 失焦，选区高亮瞬间消失。
        // 焦点留在正文，连续回车走 ta 的 searching 分支继续跳。
      } else if (e.key === 'Escape') {
        e.preventDefault();
        ta.focus();
        searching = false;
      }
    });

    /* 正文交互：
       1. 处于搜索态时，Ctrl+F 聚焦搜索；Enter/Shift+Enter 当搜索用（不进编辑换行）
       2. 其他任何输入（打字/点击）→ 退出搜索态，光标落哪改哪 */
    ta.addEventListener('mousedown', function () {
      searching = false;               // 点击正文 = 退出搜索态，开始编辑
    });
    ta.addEventListener('keydown', function (e) {
      if (searching && e.key === 'Enter') {
        e.preventDefault();            // 不允许换行把选中文本改掉
        doSearch(e.shiftKey ? false : true);
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
        e.preventDefault();
        input.focus();
        input.select();
        return;
      }
      if (searching && e.key === 'Escape') {
        searching = false;
        return;
      }
    });
  }

  /* ── 端口占用面板（查看端口 PID + 一键复制杀进程命令） ─── */
  function openPortCheck() {
    var s = shade();
    var box = document.createElement('div');
    box.className = 'cu-box';
    box.innerHTML =
      '<h2>查看端口 PID</h2>'
      + '<p class="cu-hint">输入端口号，查当前被谁占住。</p>'
      + '<div class="cu-row" style="justify-content:flex-start;margin-top:0">'
      + '  <input type="number" value="8000" min="1" max="65535" id="cuPortInput" class="cu-input" style="width:110px">'
      + '  <button class="cu-btn cu-primary" id="cuPortQuery">查询</button>'
      + '</div>'
      + '<div id="cuPortResult"></div>'
      + '<div class="cu-row"><button class="cu-btn" id="cuPortClose">关闭</button></div>';
    s.appendChild(box);

    var input = box.querySelector('#cuPortInput');
    var result = box.querySelector('#cuPortResult');
    box.querySelector('#cuPortClose').addEventListener('click', function () { s.remove(); });

    function query() {
      var port = parseInt(input.value, 10);
      if (!port || port < 1 || port > 65535) { result.innerHTML = '<p class="cu-err">端口号不合法</p>'; return; }
      result.innerHTML = '<p class="cu-hint">查询中…</p>';
      fetch('/api/port/' + port)
        .then(function (r) { if (!r.ok) throw new Error('查询失败'); return r.json(); })
        .then(function (d) { renderResult(result, d); })
        .catch(function (e) { result.innerHTML = '<p class="cu-err">' + esc(e.message) + '</p>'; });
    }

    box.querySelector('#cuPortQuery').addEventListener('click', query);
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') query(); });
    query();   // 默认查 8000
  }

  function renderResult(result, d) {
    if (!d.procs || !d.procs.length) {
      result.innerHTML = '<p class="cu-ok">端口 ' + d.port + ' 没有被占用。</p>';
      return;
    }
    var killCmd = d.procs.map(function (p) {
      return 'taskkill /F /PID ' + p.pid;
    });
    var html = '<p class="cu-warn">端口 ' + d.port + ' 被 ' + d.procs.length + ' 个进程占用：</p>';
    d.procs.forEach(function (p, i) {
      html += '<div class="cu-proc">'
        + '<div class="cu-proc-head">PID <b>' + p.pid + '</b> · ' + esc(p.name) + '</div>'
        + '<div class="cu-proc-cmd">' + esc(p.command) + '</div>'
        + '<div class="cu-row" style="margin-top:6px">'
        + '  <code class="cu-code">' + esc(killCmd[i]) + '</code>'
        + '  <button class="cu-btn cu-primary" data-copy="' + i + '">复制命令</button>'
        + '</div>'
        + '</div>';
    });
    result.innerHTML = html;
    result.querySelectorAll('[data-copy]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        copyText(killCmd[btn.dataset.copy]);
        flash('已复制：taskkill /F /PID ' + d.procs[btn.dataset.copy].pid);
      });
    });
  }

  /** 一键复制（先试剪贴板 API，不行就退回 execCommand） */
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(function () { legacyCopy(text); });
    } else {
      legacyCopy(text);
    }
  }
  function legacyCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    ta.remove();
  }

  /* ── 通用：模态壳 ─────────────────────────────────────── */
  function shade() {
    var s = document.createElement('div');
    s.className = 'cu-shade';
    s.addEventListener('click', function (e) { if (e.target === s) s.remove(); });
    document.body.appendChild(s);
    return s;
  }

  /* ── 设置面板 ─────────────────────────────────────────── */
  function openSettings() {
    var s = shade();
    var box = document.createElement('div');
    box.className = 'cu-box';
    box.innerHTML =
      '<h2>设置 · 模型通道</h2>'
      + '<p class="cu-hint">转换时用的 AI 走哪个接口。key 只存本机 app/.env。</p>'

      + '<label class="cu-hint cu-lbl">接口类型</label>'
      + '<select id="cuProvider" class="cu-input cu-select">'
      + '  <option value="anthropic">Anthropic 兼容</option>'
      + '  <option value="openai">OpenAI 兼容（deepseek、中转市场等）</option>'
      + '</select>'

      + '<label class="cu-hint cu-lbl">接口地址（留空 = 官方默认）</label>'
      + '<input id="cuBase" type="text" placeholder="https://api.deepseek.com/v1" class="cu-input">'

      + '<label class="cu-hint cu-lbl">模型名（留空 = 用默认）</label>'
      + '<input id="cuModel" type="text" placeholder="claude-sonnet-4-5 / deepseek-chat / …" class="cu-input">'

      + '<label class="cu-hint cu-lbl">API Key（留空 = 不覆盖已存的 key）</label>'
      + '<input type="password" id="cuKey" placeholder="sk-…" class="cu-input">'

      + '<div id="cuKeyNow" class="cu-hint"></div>'

      + '<h3 class="cu-h3">图片识别（识图）</h3>'
      + '<label class="cu-hint cu-lbl">识别方式</label>'
      + '<select id="cuVisionMode" class="cu-input cu-select">'
      + '  <option value="auto">自动（本地 OCR 优先，太模糊才走视觉）</option>'
      + '  <option value="ocr">只用本地 OCR（免费）</option>'
      + '  <option value="vision">只用视觉模型（按量计费）</option>'
      + '  <option value="off">关闭（不识别图片）</option>'
      + '</select>'

      + '<p class="cu-hint">视觉模型只在你主通道不支持看图、或想识别得更准时才需要。'
      + '下面三项留空 = 复用主通道。</p>'
      + '<label class="cu-hint cu-lbl">视觉模型名（可覆盖主通道）</label>'
      + '<input id="cuVModel" type="text" placeholder="qwen-vl / gpt-4o / …" class="cu-input">'
      + '<label class="cu-hint cu-lbl">视觉接口地址（可覆盖主通道）</label>'
      + '<input id="cuVBase" type="text" placeholder="留空 = 用主通道地址" class="cu-input">'
      + '<label class="cu-hint cu-lbl">视觉 API Key（留空 = 用主通道 key）</label>'
      + '<input type="password" id="cuVKey" placeholder="sk-…" class="cu-input">'
      + '<div id="cuVKeyNow" class="cu-hint"></div>'

      + '<div class="cu-row">'
      + '  <button class="cu-btn cu-primary" id="cuKeySave">保存</button>'
      + '  <button class="cu-btn" id="cuKeyCancel">取消</button>'
      + '</div>';
    s.appendChild(box);

    var provider = box.querySelector('#cuProvider');
    var base = box.querySelector('#cuBase');
    var model = box.querySelector('#cuModel');
    var now = box.querySelector('#cuKeyNow');
    var vmode = box.querySelector('#cuVisionMode');
    var vmodel = box.querySelector('#cuVModel');
    var vbase = box.querySelector('#cuVBase');
    var vnow = box.querySelector('#cuVKeyNow');

    fetch('/api/settings').then(function (r) { return r.json(); }).then(function (d) {
      provider.value = d.provider || 'anthropic';
      base.value = d.base_url || '';
      model.value = d.model || '';
      now.textContent = d.masked_key
        ? '当前 key：' + d.masked_key
        : '还没有 key——填一个才能转换。';
      vmode.value = d.vision_mode || 'auto';
      vmodel.value = d.vision_model || '';
      vbase.value = d.vision_base_url || '';
      vnow.textContent = d.masked_vision_key
        ? '视觉 key：' + d.masked_vision_key + '（复用主通道则同上）'
        : '视觉 key 未单独配（走主通道 key）';
    });

    box.querySelector('#cuKeySave').addEventListener('click', function () {
      fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: provider.value,
          base_url: base.value.trim(),
          model: model.value.trim(),
          api_key: box.querySelector('#cuKey').value.trim(),   // 留空后端不覆盖
          vision_mode: vmode.value,
          vision_model: vmodel.value.trim(),
          vision_base_url: vbase.value.trim(),
          vision_api_key: box.querySelector('#cuVKey').value.trim(),
        }),
      }).then(function (r) { return r.json(); }).then(function () {
        s.remove();
        flash('设置已保存 ✓');
      });
    });
    box.querySelector('#cuKeyCancel').addEventListener('click', function () { s.remove(); });
  }

  /* ── 转换面板 ─────────────────────────────────────────── */
  function openConverter() {
    var s = shade();
    var box = document.createElement('div');
    box.className = 'cu-box';
    box.innerHTML =
      '<h2>PDF → 导图笔记</h2>'
      + '<div class="cu-drop" tabindex="0">'
      + '  <p class="cu-drop-main">把 PDF 拖到这里，或点击选择</p>'
      + '  <p class="cu-hint">只收 .pdf。转换走当前配置的模型通道，会按量计费。</p>'
      + '</div>'
      + '<input type="file" accept=".pdf" hidden id="cuFile">'
      + '<div id="cuStage"></div>'
      + '<div class="cu-row"><button class="cu-btn" id="cuClose">关闭</button></div>';
    s.appendChild(box);
    var drop = box.querySelector('.cu-drop');
    var file = box.querySelector('#cuFile');
    var stage = box.querySelector('#cuStage');
    box.querySelector('#cuClose').addEventListener('click', function () { s.remove(); });

    drop.addEventListener('click', function () { file.click(); });
    drop.addEventListener('dragover', function (e) { e.preventDefault(); drop.classList.add('over'); });
    drop.addEventListener('dragleave', function () { drop.classList.remove('over'); });
    drop.addEventListener('drop', function (e) {
      e.preventDefault();
      drop.classList.remove('over');
      var f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) handleFile(f, stage, box);
    });
    file.addEventListener('change', function () {
      if (file.files[0]) handleFile(file.files[0], stage, box);
    });
  }

  function handleFile(f, stage, box) {
    if (!/\.pdf$/i.test(f.name)) { stage.innerHTML = '<p class="cu-err">只收 .pdf 文件</p>'; return; }
    stage.innerHTML =
      '<div class="cu-style-row">'
      + '  <label><input type="radio" name="cuStyle" value="A" checked> A · 原话派（保口语，适合复习）</label>'
      + '  <label><input type="radio" name="cuStyle" value="B"> B · 纲要派（压短句，适合速览）</label>'
      + '</div>'
      + '<button class="cu-btn cu-primary cu-go">开始转换</button>'
      + '<p class="cu-fname"></p>';
    stage.querySelector('.cu-fname').textContent = '已选：' + f.name;
    stage.querySelector('.cu-go').addEventListener('click', function () {
      var style = stage.querySelector('input[name=cuStyle]:checked').value;
      upload(f, style, stage);
    });
  }

  function upload(f, style, stage) {
    stage.innerHTML = '<p class="cu-hint">上传中…</p>';
    var fd = new FormData();
    fd.append('pdf', f);
    fetch('/api/convert?style=' + style, { method: 'POST', body: fd })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || '上传失败'); });
        return r.json();
      })
      .then(function (d) { listen(d.job_id, stage); })
      .catch(function (e) { stage.innerHTML = '<p class="cu-err">' + esc(e.message) + '</p>'; });
  }

  /* ── SSE 进度 → 阶段条 → 完成跳列表 ──────────────────── */
  function listen(jobId, stage) {
    if (state.sse) state.sse.close();
    var es = new EventSource('/api/jobs/' + jobId + '/events');
    state.sse = es;
    es.onmessage = function (ev) {
      var d = JSON.parse(ev.data);
      render(stage, d);
      if (d.phase === 'done') {
        es.close();
        state.sse = null;
        // 通知渲染器刷新列表（window.mindmap 反查约定）
        if (window.mindmap && window.mindmap.reloadIndex) {
          window.mindmap.reloadIndex();
        } else if (confirm('转换完成 ✓\n\n去 ☰ 列表就能看到「' + (d.result ? d.result.title : '') + '」。\n（渲染器是旧版，自动刷新需要手点，现在刷新页面？）')) {
          location.reload();
        }
      }
      if (d.phase === 'error') es.close();
    };
    es.onerror = function () { /* EventSource 自动重连；任务仍在后台跑 */ };
  }

  var PHASES = [
    ['check', '体检'],
    ['extract', '抽文字'],
    ['vision', '识图'],
    ['ai', 'AI 整理'],
    ['save', '登记'],
  ];

  function render(stage, d) {
    var bar = '';
    if (d.phase === 'done') {
      bar = '<p class="cu-ok">完成 ✓ ' + esc(d.message) + '</p>'
        + (d.result && d.result.gaps && d.result.gaps.length
          ? '<p class="cu-warn">缺口：' + esc(d.result.gaps.join('；')) + '</p>'
          : '');
    } else if (d.phase === 'error') {
      bar = '<div class="cu-err-box">'
        + '<p class="cu-err-head">转换失败，原因如下</p>'
        + '<p class="cu-err">' + esc(d.error || d.message || '未知错误') + '</p>'
        + '</div>';
    } else {
      var idx = PHASES.findIndex(function (p) { return p[0] === d.phase; });
      var steps = PHASES.map(function (p, i) {
        return '<span class="' + (i < idx ? 'past' : i === idx ? 'now' : '') + '">'
          + p[1] + '</span>';
      }).join(' → ');
      bar = '<p class="cu-steps">' + steps + '</p>'
        + '<div class="cu-progress"><div style="width:' + (d.progress || 4) + '%"></div></div>'
        + '<p class="cu-hint">' + esc(d.message || '') + '</p>';
    }
    var keep = stage.querySelector('.cu-fname');
    var keepTxt = keep ? keep.textContent : '';
    stage.innerHTML = bar + '<p class="cu-fname">' + esc(keepTxt) + '</p>';
  }

  /* ── 列表项增强：悬停出现 ⚙ 菜单（删除/改名/设默认） ─────── */
  function enhanceList() {
    var list = document.getElementById('treeList');
    if (!list) return;

    // 每个条目尾巴上加个小按钮（点击不触发切换）
    Array.prototype.forEach.call(list.querySelectorAll('.tl-item'), function (item) {
      if (item.querySelector('.cu-item-gear')) return;   // 已增强过（清单刷新后重画）
      var gear = document.createElement('span');
      gear.className = 'cu-item-gear';
      gear.textContent = '⋯';
      gear.title = '管理这版';
      gear.addEventListener('click', function (e) {
        e.stopPropagation();          // 别把列表项的点按变成切导图
        itemMenu(item.dataset.treeId, item.textContent.trim(), gear);
      });
      item.appendChild(gear);
    });

    // 待补充小红点：从 index.json 的 gaps 字段读
    fetch('/notes/index.json', { cache: 'no-store' }).then(function (r) { return r.json(); })
      .then(function (data) {
        (data.trees || []).forEach(function (t) {
          if (t.gaps && t.gaps.length) {
            var it = list.querySelector('[data-tree-id="' + t.id + '"]');
            if (it && !it.querySelector('.cu-gap-dot')) {
              var dot = document.createElement('span');
              dot.className = 'cu-gap-dot';
              dot.title = '有缺口（待补充）：\n' + t.gaps.join('\n');
              it.insertBefore(dot, it.firstChild);
            }
          }
        });
      }).catch(function () {});
  }

  function itemMenu(treeId, title, anchor) {
    // 简易菜单：跟随锚点位置
    document.querySelectorAll('.cu-menu').forEach(function (m) { m.remove(); });
    var menu = document.createElement('div');
    menu.className = 'cu-menu';
    var r = anchor.getBoundingClientRect();
    menu.style.top = (r.bottom + 4) + 'px';
    menu.style.left = r.left + 'px';
    menu.innerHTML =
      '<div class="cu-menu-item" data-op="rename">改名</div>'
      + '<div class="cu-menu-item" data-op="default">设为默认</div>'
      + '<div class="cu-menu-item cu-danger" data-op="delete">删除（文件+条目）</div>';
    document.body.appendChild(menu);

    menu.addEventListener('click', function (e) {
      var op = e.target.dataset.op;
      if (!op) return;
      menu.remove();
      if (op === 'rename') {
        var nt = prompt('新标题：', title);
        if (nt && nt.trim() && nt !== title) {
          fetch('/api/notes/' + treeId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: nt.trim() }),
          }).then(function () { refreshList(); });
        }
      } else if (op === 'default') {
        fetch('/api/notes/' + treeId, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ make_default: true }),
        }).then(function () { refreshList(); });
      } else if (op === 'delete') {
        if (confirm('删除「' + title + '」？\nmd 文件和清单条目都会删，不可恢复。')) {
          fetch('/api/notes/' + treeId, { method: 'DELETE' })
            .then(function () { refreshList(); });
        }
      }
    });
    setTimeout(function () {
      document.addEventListener('click', function close(e) {
        if (!menu.contains(e.target)) {
          menu.remove();
          document.removeEventListener('click', close);
        }
      });
    }, 0);
  }

  function refreshList() {
    fetch('/notes/index.json', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (window.mindmap && window.mindmap.reloadIndex) {
          // reloadIndex 内部会重读并重画列表，这里只是确保它跑
          return window.mindmap.reloadIndex().then(enhanceList);
        }
      });
  }

  /* ── 工具 ─────────────────────────────────────────────── */
  function esc(s) {
    return String(s || '').replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function flash(text) {
    // 借渲染页的 status 条闪一下
    var st = document.getElementById('status');
    if (!st) return;
    st.style.display = '';
    st.textContent = text;
    setTimeout(function () { st.style.display = 'none'; }, 2000);
  }

  injectToolbar();
  enhanceList();
})();
