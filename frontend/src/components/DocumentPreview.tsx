import { useRef, useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, AlertTriangle, FileText } from "lucide-react";
import { cn } from "../lib/cn";

interface Props {
  html: string | null;
  loading?: boolean;
  error?: string;
  className?: string;
  onQuickEdit?: (oldText: string, newText: string) => void;
  /** 用户拖拽列边框调整宽度后触发 */
  onStyleEdit?: (element: string, props: Record<string, string | number | boolean>) => void;
  /** 大纲变化时通知父组件 */
  onOutlineChange?: (items: { level: number; text: string; index: number }[]) => void;
  /** 当前可见的大纲索引变化 */
  onOutlineActive?: (index: number) => void;
  /** 当前选中元素信息（单击选中或双击编辑时） */
  onEditElement?: (info: { tagName: string; path: string; text: string; style: Record<string, string> }) => void;
  /** Excel 单元格直接编辑 */
  onCellEdit?: (path: string, newText: string) => void;
  /** Excel 单元格选择范围 */
  onCellRangeSelect?: (range: string | null, sheet?: string) => void;
}

// Injected script for column-resize and row-resize.
// Handles visual drag in-iframe; coordinates with parent for mouseup-outside-iframe.
const RESIZE_SCRIPT = `
<script>
(function() {
  // Column resize state
  var dragCol = null, dragStartX = 0, dragStartPt = 0, dragTh = null;
  // Row resize state
  var dragRow = null, dragStartY = 0, dragStartH = 0, dragRowTh = null;

  function getTable() { return document.querySelector('table'); }

  // ---- Column helpers ----
  function findBorderCol(cx) {
    var hd = document.querySelectorAll('th.col-header');
    for (var i = 0; i < hd.length; i++) {
      var r = hd[i].getBoundingClientRect();
      if (Math.abs(cx - r.right) <= 6) return { th: hd[i], idx: i };
    }
    return null;
  }
  function getColEl(idx) {
    var t = getTable(); if (!t) return null;
    var cols = t.querySelectorAll('colgroup col');
    return cols[idx + 1] || null;
  }
  function parseW(el) {
    if (!el) return 80;
    var m = el.getAttribute('style') && el.getAttribute('style').match(/width:\s*([\d.]+)\s*pt/i);
    return m ? parseFloat(m[1]) : 80;
  }

  // ---- Row helpers ----
  function findBorderRow(cy) {
    var hd = document.querySelectorAll('th.row-header');
    for (var i = 0; i < hd.length; i++) {
      var r = hd[i].getBoundingClientRect();
      if (Math.abs(cy - r.bottom) <= 6) return { th: hd[i], idx: i };
    }
    return null;
  }
  function getRowTr(th) { return th ? th.closest('tr') : null; }
  function parseH(el) {
    if (!el) return 20;
    var m = el.getAttribute('style') && el.getAttribute('style').match(/height:\s*([\d.]+)\s*pt/i);
    if (m) return parseFloat(m[1]);
    var r = el.getBoundingClientRect();
    return Math.round((r.height * 0.75) * 100) / 100;
  }

  // ---- Finish column resize ----
  function finishCol() {
    if (!dragCol || !dragTh) return;
    var p = parseW(dragCol);
    var w = Math.max(1, Math.round((p / 5.251) * 100) / 100);
    var path = dragTh.getAttribute('data-path');
    dragCol = null; dragTh = null;
    document.body.style.cursor = ''; document.body.style.userSelect = '';
    window.parent.postMessage({ type: 'col-resize-active', active: false }, '*');
    if (path && w > 0) window.parent.postMessage({ type: 'col-resize', element: path, props: { width: w } }, '*');
  }

  // ---- Finish row resize ----
  function finishRow() {
    if (!dragRow || !dragRowTh) return;
    var tr = getRowTr(dragRowTh);
    var p = tr ? parseH(tr) : dragStartH;
    var h = Math.max(5, Math.round(p * 100) / 100);
    var path = dragRowTh.getAttribute('data-path');
    dragRow = null; dragRowTh = null;
    document.body.style.cursor = ''; document.body.style.userSelect = '';
    window.parent.postMessage({ type: 'row-resize-active', active: false }, '*');
    if (path && h > 0) window.parent.postMessage({ type: 'row-resize', element: path, props: { height: h } }, '*');
  }

  // ---- Hover cursors ----
  document.addEventListener('mousemove', function(e) {
    if (dragCol || dragRow) return;
    var t = e.target;
    if (t && t.closest('thead')) {
      var bc = findBorderCol(e.clientX);
      document.body.style.cursor = bc ? 'col-resize' : '';
    } else if (t && t.closest('tbody')) {
      var br = findBorderRow(e.clientY);
      document.body.style.cursor = br ? 'row-resize' : '';
    } else {
      document.body.style.cursor = '';
    }
  });

  // ---- Start drag ----
  document.addEventListener('mousedown', function(e) {
    if (e.button !== 0) return;
    var t = e.target;
    if (t && t.closest('thead')) {
      var bc = findBorderCol(e.clientX);
      if (!bc) return;
      e.preventDefault();
      var el = getColEl(bc.idx); if (!el) return;
      dragTh = bc.th; dragCol = el;
      dragStartX = e.clientX; dragStartPt = parseW(el);
      document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
      window.parent.postMessage({ type: 'col-resize-active', active: true }, '*');
    } else if (t && t.closest('tbody')) {
      var br = findBorderRow(e.clientY);
      if (!br) return;
      e.preventDefault();
      var tr = getRowTr(br.th); if (!tr) return;
      dragRowTh = br.th; dragRow = tr;
      dragStartY = e.clientY; dragStartH = parseH(tr);
      document.body.style.cursor = 'row-resize'; document.body.style.userSelect = 'none';
      window.parent.postMessage({ type: 'row-resize-active', active: true }, '*');
    }
  });

  // ---- Drag update ----
  document.addEventListener('mousemove', function(e) {
    if (dragCol) {
      var newColPt = Math.max(10, dragStartPt + (e.clientX - dragStartX) * 0.75);
      dragCol.style.width = newColPt + 'pt';
      var tbl = getTable();
      if (tbl) {
        var total = 0;
        var cs = tbl.querySelectorAll('colgroup col');
        for (var ci = 0; ci < cs.length; ci++) {
          var sw = cs[ci].getAttribute('style') && cs[ci].getAttribute('style').match(/width:\s*([\d.]+)\s*pt/i);
          total += sw ? parseFloat(sw[1]) : 0;
        }
        tbl.style.width = Math.max(total, 50) + 'pt';
      }
    } else if (dragRow) {
      dragRow.style.height = Math.max(5, dragStartH + (e.clientY - dragStartY) * 0.75) + 'pt';
    }
  });

  // ---- Mouseup inside iframe ----
  document.addEventListener('mouseup', function(e) {
    if (dragCol) finishCol(); else if (dragRow) finishRow();
  });

  // ---- Mouseup outside iframe ----
  window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'col-resize-finish' && dragCol) finishCol();
    if (e.data && e.data.type === 'row-resize-finish' && dragRow) finishRow();
  });
})();
</script>
`;

// Injected script for inline editing.// Injected script for inline editing.
// Double-click to edit. Escape to cancel. Save triggers:
//   - Click outside element (inside iframe) → mousedown handler
//   - Click outside iframe → parent sends "quick-edit-finish" message
const EDIT_SCRIPT = `
<script>
(function() {
  var el = null, oldText = '';
  var el_isCell = false, el_path = '';
  var selectedEl = null;

  // ── Excel 单元格选择 ──
  var selStart = null, selEnd = null;
  var cellMouseDown = false;

  // ★ 覆盖层：保证选区始终显示为完整矩形（挂载到 .table-wrapper 内）
  var overlay = document.createElement('div');
  overlay.id = 'excel-selection-overlay';
  overlay.style.cssText = 'position:absolute;pointer-events:none;z-index:100;border:2px solid #217346;background:rgba(33,115,70,0.08);display:none;';

  // 辅助函数：获取单元格实际占用的行列数
  function getCellSpan(td) {
    var cs = td.getAttribute('colspan');
    var rs = td.getAttribute('rowspan');
    return {
      colspan: cs ? parseInt(cs, 10) : 1,
      rowspan: rs ? parseInt(rs, 10) : 1
    };
  }

  function parseCellPath(path) {
    // path = "/采购计划样表/C6" → split("/") → ["", "采购计划样表", "C6"]
    var parts = path.split('/');
    var cellRef = parts[parts.length - 1];  // "C6"
    if (!cellRef) return null;
    var colMatch = cellRef.match(/^([A-Z]+)([0-9]+)$/);
    if (!colMatch) return null;
    var colLetters = colMatch[1], colIdx = 0;
    for (var i = 0; i < colLetters.length; i++) colIdx = colIdx * 26 + (colLetters.charCodeAt(i) - 64);
    return { col: colLetters, colIdx: colIdx - 1, row: parseInt(colMatch[2], 10) - 1 };
  }
  function colIdxToLetter(idx) {
    var s = '', i = idx + 1;
    while (i > 0) { var r = (i - 1) % 26; s = String.fromCharCode(65 + r) + s; i = Math.floor((i - 1) / 26); }
    return s;
  }
  function formatCellStr(info) { return colIdxToLetter(info.colIdx) + (info.row + 1); }
  function formatRangeStr(a, b) { var s = formatCellStr(a), e = formatCellStr(b); return s === e ? s : s + ':' + e; }
  function clearCellSelection() {
    var cells = document.querySelectorAll('td[data-path]');
    for (var i = 0; i < cells.length; i++) { cells[i].style.backgroundColor = ''; cells[i].style.outline = ''; cells[i].style.outlineOffset = ''; }
    // 清除行背景
    var rows = document.querySelectorAll('tr[data-row]');
    for (var i = 0; i < rows.length; i++) { rows[i].style.backgroundColor = ''; rows[i].style.outline = ''; }
    // 隐藏覆盖层
    var ov = document.getElementById('excel-selection-overlay');
    if (ov) ov.style.display = 'none';
  }
  // ★ 定位覆盖层：计算选区完整矩形的物理位置
  function positionOverlay(minR, maxR, minC, maxC) {
    var ov = document.getElementById('excel-selection-overlay');
    if (!ov) return;
    // 找到选区左上角和右下角的 td 元素
    var topLeft = null, bottomRight = null;
    var all = document.querySelectorAll('td[data-path]');
    for (var i = 0; i < all.length; i++) {
      var info = parseCellPath(all[i].getAttribute('data-path') || '');
      if (!info) continue;
      if (info.row === minR && info.colIdx === minC) topLeft = all[i];
      if (info.row === maxR && info.colIdx === maxC) bottomRight = all[i];
      if (topLeft && bottomRight) break;
    }
    // fallback：如果找不到精确匹配，取范围内任意单元格
    if (!topLeft) {
      for (var i = 0; i < all.length; i++) {
        var info = parseCellPath(all[i].getAttribute('data-path') || '');
        if (info && info.row === minR) { topLeft = all[i]; break; }
      }
    }
    if (!bottomRight) {
      for (var i = 0; i < all.length; i++) {
        var info = parseCellPath(all[i].getAttribute('data-path') || '');
        if (info && info.row === maxR) { bottomRight = all[i]; break; }
      }
    }
    if (!topLeft || !bottomRight) { ov.style.display = 'none'; return; }
    // 把覆盖层挂在 .table-wrapper 内部，position:absolute 自然相对于 wrapper 定位
    var wrapper = document.querySelector('.table-wrapper') || document.body;
    if (ov.parentNode !== wrapper) wrapper.appendChild(ov);
    var wr = wrapper.getBoundingClientRect();
    var r1 = topLeft.getBoundingClientRect();
    var r2 = bottomRight.getBoundingClientRect();
    ov.style.display = 'block';
    ov.style.left = (r1.left - wr.left) + 'px';
    ov.style.top = (r1.top - wr.top) + 'px';
    ov.style.width = (r2.right - r1.left) + 'px';
    ov.style.height = (r2.bottom - r1.top) + 'px';
  }

  function highlightRange(a, b) {
    clearCellSelection();
    // ★ 使用物理范围（考虑 colspan/rowspan）计算矩形
    var minR = Math.min(a.row, b.row);
    var maxR = Math.max(a.bottomRow !== undefined ? a.bottomRow : a.row, b.bottomRow !== undefined ? b.bottomRow : b.row);
    var minC = Math.min(a.colIdx, b.colIdx);
    var maxC = Math.max(a.rightCol !== undefined ? a.rightCol : a.colIdx, b.rightCol !== undefined ? b.rightCol : b.colIdx);

    // ★ 关键修复：扩展范围以覆盖选区内所有合并单元格的完整行列
    // 例如 A6(rowspan=2) 在选区内时，选区要自动扩展到第7行
    var changed = true;
    while (changed) {
      changed = false;
      var all = document.querySelectorAll('td[data-path]');
      for (var i = 0; i < all.length; i++) {
        var info = parseCellPath(all[i].getAttribute('data-path') || '');
        if (!info) continue;
        if (info.row >= minR && info.row <= maxR && info.colIdx >= minC && info.colIdx <= maxC) {
          var span = getCellSpan(all[i]);
          var cellBottom = info.row + span.rowspan - 1;
          var cellRight = info.colIdx + span.colspan - 1;
          if (cellBottom > maxR) { maxR = cellBottom; changed = true; }
          if (cellRight > maxC) { maxC = cellRight; changed = true; }
        }
      }
    }

    // 整行高亮：覆盖选中行整个宽度（即使某些列没有 td）
    var rows = document.querySelectorAll('tr[data-row]');
    for (var i = 0; i < rows.length; i++) {
      var rowAttr = rows[i].getAttribute('data-row') || '';
      var parts = rowAttr.split('-');
      var dataRow = parseInt(parts[parts.length - 1], 10) - 1;
      if (!isNaN(dataRow) && dataRow >= minR && dataRow <= maxR) {
        rows[i].style.backgroundColor = 'rgba(33,115,70,0.06)';
      }
    }
    // 单元格高亮：给选中的具体单元格加边框（使用扩展后的范围）
    var all = document.querySelectorAll('td[data-path]');
    for (var i = 0; i < all.length; i++) {
      var info = parseCellPath(all[i].getAttribute('data-path') || '');
      if (!info) continue;
      if (info.row >= minR && info.row <= maxR && info.colIdx >= minC && info.colIdx <= maxC) {
        all[i].style.backgroundColor = 'rgba(33,115,70,0.12)';
        all[i].style.outline = '2px solid #217346';
        all[i].style.outlineOffset = '-1px';
      }
    }
    // ★ 覆盖层：保证选区始终显示为完整矩形
    positionOverlay(minR, maxR, minC, maxC);
    return formatRangeStr({ colIdx: minC, row: minR }, { colIdx: maxC, row: maxR });
  }

  // Walk up to a meaningful block-level container
  function findBlock(target) {
    var blockTags = ['DIV','P','LI','H1','H2','H3','H4','H5','H6','TD','TH','BLOCKQUOTE','PRE','SPAN'];
    var t = target;
    while (t && t.parentNode && t.parentNode !== document.body) {
      if (blockTags.indexOf(t.tagName) >= 0 && t.textContent.trim()) break;
      t = t.parentNode;
    }
    if (t === document.body || !t.textContent.trim()) {
      t = target;
      while (t && t.parentNode && !t.textContent.trim() && blockTags.indexOf(t.tagName) < 0) {
        t = t.parentNode;
      }
    }
    return (t && t !== document.body) ? t : null;
  }

  // Send element info to parent (activates the formatting toolbar)
  function notifySelected(t) {
    if (!t) return;
    selectedEl = t;
    var cs = window.getComputedStyle(t);
    var dataPath = t.getAttribute('data-path') || '';
    var text = (t.innerText || t.textContent || '').trim().substring(0, 2000);
    window.parent.postMessage({
      type: 'edit-element-selected',
      tagName: t.tagName,
      path: dataPath,
      text: text,
      style: {
        fontWeight: cs.fontWeight,
        fontStyle: cs.fontStyle,
        textDecoration: cs.textDecoration,
        fontSize: cs.fontSize,
        color: cs.color,
      }
    }, '*');
  }

  // mouseup → check if user selected text
  document.addEventListener('mouseup', function(e) {
    if (el) return;
    var wasCellDrag = cellMouseDown;
    cellMouseDown = false;
    setTimeout(function() {
      var sel = window.getSelection();
      var selText = sel ? sel.toString().trim() : '';
      if (wasCellDrag) return;
      if (selText && selectedEl && selText !== (selectedEl.innerText || '').trim()) {
        notifySelectedFromText(selText);
      } else if (selText) {
        var t = sel.anchorNode ? (sel.anchorNode.parentElement || sel.anchorNode.parentNode) : null;
        var block = t ? findBlock(t) : null;
        if (block) notifySelected(block);
        else notifySelectedFromText(selText);
      } else {
        if (selectedEl && !selStart) {
          selectedEl = null;
          window.parent.postMessage({ type: 'edit-element-deselected' }, '*');
        }
      }
    }, 10);
  });

  // selectionchange
  document.addEventListener('selectionchange', function() {
    if (el) return;
    if (selStart) return; // 单元格选择模式不反选
    var sel = window.getSelection();
    var selText = sel ? sel.toString().trim() : '';
    if (!selText && selectedEl) {
      selectedEl = null;
      window.parent.postMessage({ type: 'edit-element-deselected' }, '*');
    }
  });

  function notifySelectedFromText(text) {
    selectedEl = null;
    window.parent.postMessage({
      type: 'edit-element-selected',
      tagName: 'TEXT', path: '',
      text: text.substring(0, 2000),
      style: { fontWeight: '400', fontStyle: 'normal', textDecoration: 'none', fontSize: '14px', color: '#000000' }
    }, '*');
  }

  // ── 单元格选择（支持合并单元格） ──
  // 辅助函数：从 td 构建包含物理范围的位置对象
  function makeCellPos(td) {
    var info = parseCellPath(td.getAttribute('data-path') || '');
    if (!info) return null;
    var span = getCellSpan(td);
    return {
      colIdx: info.colIdx,
      row: info.row,
      rightCol: info.colIdx + span.colspan - 1,
      bottomRow: info.row + span.rowspan - 1
    };
  }

  document.addEventListener('mousedown', function(e) {
    if (el) return;
    var td = e.target.closest ? e.target.closest('td[data-path]') : null;
    if (!td) return;
    notifySelected(td);
    cellMouseDown = true;
    var pos = makeCellPos(td);
    if (!pos) return;
    selStart = pos; selEnd = JSON.parse(JSON.stringify(pos));
    var range = highlightRange(selStart, selEnd);
    var sheetName = (td.getAttribute('data-path') || '').split('/')[1] || '';
    window.parent.postMessage({ type: 'cell-range-select', range: range, sheet: sheetName }, '*');
  });

  document.addEventListener('mousemove', function(e) {
    if (!cellMouseDown || !selStart || el) return;
    var td = e.target.closest ? e.target.closest('td[data-path]') : null;
    if (!td) return;
    var pos = makeCellPos(td);
    if (!pos) return;
    selEnd = pos;
    var range = highlightRange(selStart, selEnd);
    var sheetName = (td.getAttribute('data-path') || '').split('/')[1] || '';
    window.parent.postMessage({ type: 'cell-range-select', range: range, sheet: sheetName }, '*');
  });

  document.addEventListener('selectstart', function(e) {
    if (cellMouseDown) e.preventDefault();
  });

  // 点击非 td 区域清除选区
  document.addEventListener('mousedown', function(e) {
    if (el) return;
    var td = e.target.closest ? e.target.closest('td[data-path]') : null;
    if (!td && selStart) {
      selStart = null; selEnd = null;
      clearCellSelection();
      window.parent.postMessage({ type: 'cell-range-select', range: null }, '*');
    }
  });

  // ── 双击编辑（支持 Excel 单元格） ──
  document.addEventListener('dblclick', function(e) {
    var t = e.target;
    if (!t || t.tagName === 'BODY' || t.tagName === 'HTML' || t.tagName === 'SCRIPT' || t.tagName === 'STYLE') return;

    // Excel 单元格直接编辑（通过 data-path 精确定位）
    var td = t.closest ? t.closest('td[data-path]') : null;
    if (td) {
      var cellPath = td.getAttribute('data-path') || '';
      var cellText = (td.innerText || td.textContent || '').trim();
      td.contentEditable = 'true'; td.focus();
      try { var r = document.createRange(); r.selectNodeContents(td); var s = window.getSelection(); s.removeAllRanges(); s.addRange(r); } catch(_) {}
      el = td; el_isCell = true; el_path = cellPath; oldText = cellText;
      notifySelected(td);
      window.parent.postMessage({ type: 'quick-edit-active', active: true }, '*');
      e.preventDefault();
      return;
    }

    // 普通元素编辑
    var block = findBlock(t);
    if (!block) return;
    var txt = (block.innerText || block.textContent).trim();
    if (!txt) return;
    block.contentEditable = 'true'; block.focus();
    try { var r = document.createRange(); r.selectNodeContents(block); var s = window.getSelection(); s.removeAllRanges(); s.addRange(r); } catch(_) {}
    el = block; el_isCell = false; el_path = ''; oldText = txt;
    notifySelected(block);
    window.parent.postMessage({ type: 'quick-edit-active', active: true }, '*');
  });

  // Escape to cancel
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && el) { e.preventDefault(); cancel(); }
  });

  // Click inside iframe but outside editing element → save
  document.addEventListener('mousedown', function(e) {
    if (!el) return;
    if (el === e.target || el.contains(e.target)) return;
    finish();
  }, true);

  // Listen for parent messages
  window.addEventListener('message', function(e) {
    if (e.data?.type === 'quick-edit-finish' && el) finish();
    if (e.data?.type === 'apply-style' && selectedEl) {
      var props = e.data.props;
      for (var k in props) {
        if (k === 'bold') selectedEl.style.fontWeight = props[k] ? 'bold' : 'normal';
        else if (k === 'italic') selectedEl.style.fontStyle = props[k] ? 'italic' : 'normal';
        else if (k === 'underline') selectedEl.style.textDecoration = props[k] ? 'underline' : 'none';
        else if (k === 'size') selectedEl.style.fontSize = props[k] + 'pt';
        else if (k === 'color') selectedEl.style.color = props[k];
      }
      notifySelected(selectedEl);
    }
  });

  function finish() {
    if (!el) return;
    var n = (el.innerText || el.textContent).trim();
    el.contentEditable = 'false';
    if (el_isCell && el_path) {
      // Excel 单元格：用 data-path 精确定位
      if (n !== oldText) window.parent.postMessage({ type: 'cell-edit', path: el_path, new_text: n }, '*');
    } else {
      if (n && n !== oldText) window.parent.postMessage({ type: 'quick-edit', old_text: oldText, new_text: n }, '*');
    }
    el = null; oldText = ''; el_isCell = false; el_path = '';
    window.parent.postMessage({ type: 'quick-edit-active', active: false }, '*');
  }

  function cancel() {
    if (!el) return;
    el.innerText = oldText;
    el.contentEditable = 'false';
    el = null; oldText = ''; el_isCell = false; el_path = '';
    window.parent.postMessage({ type: 'quick-edit-active', active: false }, '*');
  }
})();
</script>
`;

export function DocumentPreview({ html, loading, error, className, onQuickEdit, onStyleEdit, onOutlineChange, onOutlineActive, onEditElement, onCellEdit, onCellRangeSelect }: Props) {
  const { t } = useTranslation();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const editHandlerRef = useRef(onQuickEdit);
  const styleHandlerRef = useRef(onStyleEdit);
  const outlineHandlerRef = useRef(onOutlineChange);
  const outlineActiveHandlerRef = useRef(onOutlineActive);
  const editElementHandlerRef = useRef(onEditElement);
  const cellEditHandlerRef = useRef(onCellEdit);
  const cellRangeSelectHandlerRef = useRef(onCellRangeSelect);
  const [editing, setEditing] = useState(false);
  const [resizing, setResizing] = useState(false);
  const resizeActive = useRef(false);
  // ── Scroll position memory (survives srcDoc refresh) ──
  const savedScroll = useRef<number>(0);
  const prevHtml = useRef<string | null>(null);
  // Track scroll position from inside iframe
  const scrollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  editHandlerRef.current = onQuickEdit;
  styleHandlerRef.current = onStyleEdit;
  outlineHandlerRef.current = onOutlineChange;
  outlineActiveHandlerRef.current = onOutlineActive;
  editElementHandlerRef.current = onEditElement;
  cellEditHandlerRef.current = onCellEdit;
  cellRangeSelectHandlerRef.current = onCellRangeSelect;

  // Listen for messages from iframe
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      const data = e.data;
      if (!data) return;
      if (data.type === "quick-edit" && data.old_text && data.new_text) {
        editHandlerRef.current?.(data.old_text, data.new_text);
      } else if (data.type === "quick-edit-active") {
        setEditing(!!data.active);
      } else if (data.type === "col-resize" && data.element && data.props) {
        setResizing(true);
        styleHandlerRef.current?.(data.element, data.props);
        setTimeout(() => setResizing(false), 800);
      } else if (data.type === "row-resize" && data.element && data.props) {
        setResizing(true);
        styleHandlerRef.current?.(data.element, data.props);
        setTimeout(() => setResizing(false), 800);
      } else if (data.type === "col-resize-active" || data.type === "row-resize-active") {
        resizeActive.current = !!data.active;
        if (data.active) {
          document.body.style.cursor = data.type === "row-resize-active" ? 'row-resize' : 'col-resize';
          document.body.style.userSelect = 'none';
        } else {
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
        }
      } else if (data.type === "doc-outline" && data.items) {
        outlineHandlerRef.current?.(data.items as { level: number; text: string; index: number }[]);
      } else if (data.type === "doc-outline-active") {
        outlineActiveHandlerRef.current?.(data.index as number);
      } else if (data.type === "edit-element-selected") {
        editElementHandlerRef.current?.({
          tagName: data.tagName,
          path: data.path,
          text: data.text || "",
          style: data.style,
        });
      } else if (data.type === "edit-element-deselected") {
        editElementHandlerRef.current?.(null as any);
      } else if (data.type === "cell-edit" && data.path && data.new_text !== undefined) {
        cellEditHandlerRef.current?.(data.path as string, data.new_text as string);
      } else if (data.type === "cell-range-select") {
        cellRangeSelectHandlerRef.current?.(data.range || null, data.sheet as string | undefined);
      } else if (data.type === "doc-scroll-position") {
        savedScroll.current = data.scrollTop as number;
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  // Forward mouseup outside iframe → col/row-resize-finish to iframe
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!resizeActive.current) return;
      const iframe = iframeRef.current;
      if (!iframe) return;
      const rect = iframe.getBoundingClientRect();
      if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) {
        iframe.contentWindow?.postMessage({ type: 'col-resize-finish' }, '*');
        iframe.contentWindow?.postMessage({ type: 'row-resize-finish' }, '*');
      }
    };
    window.addEventListener("mouseup", handler);
    return () => window.removeEventListener("mouseup", handler);
  }, []);

  // When editing is active, listen for clicks on the parent page
  // to send "finish" to the iframe.
  useEffect(() => {
    if (!editing) return;
    const handler = (e: MouseEvent) => {
      const iframe = iframeRef.current;
      if (!iframe) return;
      // Check if click is outside the iframe
      const rect = iframe.getBoundingClientRect();
      const x = e.clientX, y = e.clientY;
      if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
        iframe.contentWindow?.postMessage({ type: "quick-edit-finish" }, "*");
      }
    };
    // Use capture phase to catch clicks before they reach iframe
    window.addEventListener("mousedown", handler, true);
    return () => window.removeEventListener("mousedown", handler, true);
  }, [editing]);

  // Before html changes, grab current scroll position from the iframe
  useEffect(() => {
    if (prevHtml.current !== null && prevHtml.current !== html) {
      const iframe = iframeRef.current;
      try {
        const win = iframe?.contentWindow;
        if (win) savedScroll.current = win.scrollY || 0;
      } catch {}
    }
    prevHtml.current = html;
  }, [html]);

  // Restore scroll position after iframe reloads
  const handleIframeLoad = useCallback(() => {
    const iframe = iframeRef.current;
    try {
      const win = iframe?.contentWindow;
      if (win && savedScroll.current > 0) {
        win.scrollTo(0, savedScroll.current);
      }
    } catch {}
  }, []);

  if (loading && !error) {
    return (
      <div className={cn("flex flex-col items-center justify-center h-full gap-3", className)}>
        <Loader2 size={24} className="animate-spin text-[var(--text-tertiary)]" />
        <span className="text-xs text-[var(--text-tertiary)]">{t("document.loadingPreview")}</span>
      </div>
    );
  }

  if (loading && error) {
    // Loading with a status message (e.g. OfficeCLI install progress)
    return (
      <div className={cn("flex flex-col items-center justify-center h-full gap-3 p-6", className)}>
        <Loader2 size={24} className="animate-spin text-[var(--accent)]" />
        <span className="text-xs text-[var(--accent)] text-center whitespace-pre-line">{error}</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className={cn("flex flex-col items-center justify-center h-full gap-3 p-6", className)}>
        <AlertTriangle size={24} className="text-[var(--danger)]" />
        <span className="text-xs text-[var(--danger)] text-center">{error}</span>
      </div>
    );
  }

  if (!html) {
    return (
      <div className={cn("flex flex-col items-center justify-center h-full gap-3", className)}>
        <FileText size={28} className="text-[var(--text-tertiary)]" opacity={0.4} />
        <span className="text-xs text-[var(--text-tertiary)]">{t("document.previewFailed")}</span>
      </div>
    );
  }

  // Injected script for outline extraction + scroll tracking + highlight + element info.
const OUTLINE_SCRIPT = `
<script>
(function() {
  function extractOutline() {
    var headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
    var items = [];
    headings.forEach(function(h, i) {
      h.setAttribute('data-outline-idx', i);
      items.push({
        level: parseInt(h.tagName[1]),
        text: h.textContent.trim().substring(0, 80),
        index: i
      });
    });
    window.parent.postMessage({ type: 'doc-outline', items: items }, '*');
  }

  setTimeout(extractOutline, 200);

  var outlineTimer = null;
  var observer = new MutationObserver(function() {
    if (outlineTimer) clearTimeout(outlineTimer);
    outlineTimer = setTimeout(extractOutline, 300);
  });
  observer.observe(document.body, { childList: true, subtree: true });

  // Scroll tracking — update active heading + report scroll position to parent
  var scrollTimer = null;
  window.addEventListener('scroll', function() {
    // Report scroll position immediately (low cost)
    window.parent.postMessage({ type: 'doc-scroll-position', scrollTop: window.scrollY }, '*');
    if (scrollTimer) return;
    scrollTimer = setTimeout(function() {
      scrollTimer = null;
      var headings = document.querySelectorAll('[data-outline-idx]');
      var activeIdx = 0;
      headings.forEach(function(h) {
        var rect = h.getBoundingClientRect();
        if (rect.top < 80) {
          activeIdx = parseInt(h.getAttribute('data-outline-idx'));
        }
      });
      window.parent.postMessage({ type: 'doc-outline-active', index: activeIdx }, '*');
    }, 100);
  });

  // Listen for scroll requests from parent
  window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'doc-outline-scroll') {
      var el = document.querySelector('[data-outline-idx="' + e.data.index + '"]');
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });

  // Listen for highlight requests from parent
  window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'highlight-element') {
      var target = null;
      // Try data-path first
      if (e.data.path) {
        target = document.querySelector('[data-path="' + e.data.path + '"]');
      }
      // Fallback: try text matching
      if (!target && e.data.text) {
        var candidates = document.querySelectorAll('p, td, h1, h2, h3, h4, span, div');
        for (var i = 0; i < candidates.length; i++) {
          if (candidates[i].textContent.includes(e.data.text)) {
            target = candidates[i];
            break;
          }
        }
      }
      if (!target) return;
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      var orig = target.style.backgroundColor;
      var origTransition = target.style.transition;
      target.style.transition = 'background-color 0.3s';
      target.style.backgroundColor = 'rgba(255, 230, 0, 0.35)';
      setTimeout(function() {
        target.style.backgroundColor = orig;
        setTimeout(function() { target.style.transition = origTransition; }, 500);
      }, 2500);
    }
  });
})();
</script>
`;

const allScripts = `${RESIZE_SCRIPT}\n${EDIT_SCRIPT}\n${OUTLINE_SCRIPT}`;
  const injectedHtml = html.includes("</body>")
    ? html.replace("</body>", `${allScripts}\n</body>`)
    : html + allScripts;

  return (
    <div className={cn("relative h-full", className)}>
      {editing && (
        <div className="absolute top-2 right-2 z-40 px-2 py-1 rounded-lg text-[10px] bg-blue-500 text-white shadow-md">
          Editing... (click outside to save)
        </div>
      )}
      {resizing && (
        <div className="absolute top-2 left-2 z-40 px-2 py-1 rounded-lg text-[10px] bg-green-600 text-white shadow-md">
          Resizing...
        </div>
      )}
      <iframe
        ref={iframeRef}
        srcDoc={injectedHtml}
        title="Document Preview"
        className="w-full h-full border-0"
        sandbox="allow-scripts allow-same-origin"
        style={{ background: "#fff" }}
        onLoad={handleIframeLoad}
      />
    </div>
  );
}
