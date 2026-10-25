/* 静态部署（GitHub Pages）下的本地编辑：
   改动写进 localStorage，只影响当前浏览器；可导出 .md 带走。
   需要后端的功能（转换 / 设置 / 改名 / 删除）不在这里。 */
(function () {
  'use strict';

  var PREFIX = 'mindmap.local-md.v1:';
  var panel = null;

  function currentId() {
    var el = document.querySelector('.mm-canvas.is-active');
    return el && el.dataset.treeId;
  }

  function treeOf(id) {
    var mm = window.mindmap;
    if (!mm || !Array.isArray(mm.trees)) return null;
    return mm.trees.find(function (t) { return t.id === id; }) || null;
  }

  function isSaved(id) {
    try { return localStorage.getItem(PREFIX + id) !== null; }
    catch (err) { return false; }
  }

  function saveLocal(id, md) {
    try { localStorage.setItem(PREFIX + id, md); return true; }
    catch (err) { return false; }
  }

  function dropLocal(id) {
    try { localStorage.removeItem(PREFIX + id); } catch (err) {}
  }

  function flash(msg, isErr) {
    if (!panel) return;
    var el = panel.querySelector('.se-flash');
    if (!el) return;
    el.textContent = msg;
    el.classList.toggle('err', !!isErr);
    clearTimeout(flash.timer);
    flash.timer = setTimeout(function () { el.textContent = ''; }, 3200);
  }

  function fill() {
    if (!panel) return;
    var id = currentId();
    var tree = treeOf(id);
    if (!tree) return;
    panel.querySelector('.se-title').textContent =
      tree.title + (isSaved(id) ? ' · 本地修改版' : '');
    var ta = panel.querySelector('.se-ta');
    ta.value = tree.md || '';
    ta.scrollTop = 0;
    ta.selectionStart = ta.selectionEnd = 0;
    var f = panel.querySelector('.se-flash');
    if (f) f.textContent = '';
  }

  function openPanel() {
    if (panel) { fill(); panel.querySelector('.se-ta').focus(); return; }

    panel = document.createElement('div');
    panel.className = 'se-panel';
    panel.innerHTML =
      '<div class="se-inner">'
      + '<div class="se-head"><h2>✎ 编辑导图</h2><span class="se-title"></span></div>'
      + '<p class="se-hint">修改只保存在<b>当前浏览器</b>，不会上传；换浏览器或清缓存会丢失。<br>'
      + '要永久保存请点 <b>导出 .md</b>。缩进 2 空格，# 标题 · - 条目。</p>'
      + '<textarea class="se-ta" spellcheck="false" wrap="off"></textarea>'
      + '<div class="se-row">'
      + '<button class="se-btn se-primary" data-se="save">保存并更新</button>'
      + '<button class="se-btn" data-se="export">导出 .md</button>'
      + '<button class="se-btn se-danger" data-se="reset">恢复原版</button>'
      + '<button class="se-btn" data-se="close">关闭</button>'
      + '</div>'
      + '<div class="se-flash"></div>'
      + '</div>';
    document.body.appendChild(panel);
    document.body.classList.add('se-split');

    panel.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-se]');
      if (!btn) return;
      var act = btn.dataset.se;
      if (act === 'save') doSave();
      else if (act === 'export') doExport();
      else if (act === 'reset') doReset();
      else if (act === 'close') closePanel();
    });

    panel.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.stopPropagation(); closePanel(); }
      else if ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === 's') {
        e.preventDefault();
        doSave();
      }
    });

    fill();
    panel.querySelector('.se-ta').focus();
    setTimeout(function () { try { window.mindmap.fit(); } catch (err) {} }, 60);
  }

  function doSave() {
    if (!panel) return;
    var ta = panel.querySelector('.se-ta');
    var content = ta.value;
    if (!content.trim()) { flash('内容不能为空', true); return; }
    if (!/^\s*# /.test(content)) { flash("第一行必须是 '# 标题'", true); return; }

    var id = currentId();
    if (!id) { flash('找不到当前导图', true); return; }
    if (!saveLocal(id, content)) { flash('保存失败：浏览器存储不可用', true); return; }

    var tree = treeOf(id);
    if (tree) tree.md = content;
    if (window.mindmap && window.mindmap.reloadActive) {
      window.mindmap.reloadActive(content);
    }
    panel.querySelector('.se-title').textContent = tree.title + ' · 本地修改版';
    flash('已保存到本机浏览器 ✓');
  }

  function doExport() {
    if (!panel) return;
    var id = currentId();
    if (!id) return;
    var md = panel.querySelector('.se-ta').value;
    var blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = id + '.md';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    flash('已导出 ' + id + '.md');
  }

  function doReset() {
    if (!panel) return;
    var id = currentId();
    var tree = treeOf(id);
    if (!id || !tree) return;
    if (!isSaved(id)) { flash('当前就是原始版本'); return; }
    if (!tree.serverMd) { flash('拿不到原始版本，请刷新页面再试', true); return; }
    if (!confirm('放弃本浏览器里的修改，恢复为线上原始版本？')) return;

    dropLocal(id);
    tree.md = tree.serverMd;
    panel.querySelector('.se-ta').value = tree.serverMd;
    if (window.mindmap && window.mindmap.reloadActive) {
      window.mindmap.reloadActive(tree.serverMd);
    }
    panel.querySelector('.se-title').textContent = tree.title;
    flash('已恢复原始版本');
  }

  function closePanel() {
    if (!panel) return;
    panel.remove();
    panel = null;
    document.body.classList.remove('se-split');
    setTimeout(function () { try { window.mindmap.fit(); } catch (err) {} }, 60);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('editBtn');
    if (btn) btn.addEventListener('click', function (e) { e.preventDefault(); openPanel(); });

    // 面板开着时切导图，内容跟着换
    var list = document.getElementById('treeList');
    if (list) list.addEventListener('click', function () {
      if (panel) setTimeout(fill, 0);
    });
  });
})();
