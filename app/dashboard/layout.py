# app/dashboard/layout.py

from __future__ import annotations


SHARED_STYLES = """
:root {
  /* ── Neutral scale ── */
  --gray-50: #f8fafc;
  --gray-100: #f1f5f9;
  --gray-200: #e2e8f0;
  --gray-300: #cbd5e1;
  --gray-400: #94a3b8;
  --gray-500: #64748b;
  --gray-600: #475569;
  --gray-700: #334155;
  --gray-800: #1e293b;
  --gray-900: #0f172a;

  /* ── Green accent (preserved) ── */
  --green-50: #ecfdf5;
  --green-100: #d1fae5;
  --green-200: #a7f3d0;
  --green-300: #6ee7b7;
  --green-500: #10b981;
  --green-600: #059669;
  --green-700: #047857;
  --green-800: #065f46;

  /* ── Semantic ── */
  --bg: #f8fafc;
  --bg-alt: #f1f5f9;
  --card: #ffffff;
  --text: #0f172a;
  --text-secondary: #475569;
  --muted: #64748b;
  --line: #e2e8f0;
  --line-light: #f1f5f9;
  --accent: #059669;
  --accent-dark: #047857;
  --accent-light: #d1fae5;
  --soft: #f1f5f9;
  --danger: #dc2626;
  --danger-light: #fef2f2;
  --warning: #d97706;
  --warning-light: #fffbeb;
  --info: #2563eb;
  --info-light: #eff6ff;
  --radius: 12px;
  --radius-sm: 8px;
  --radius-lg: 16px;
  --radius-xl: 20px;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;

  /* ── Shadows ── */
  --shadow-xs: 0 1px 2px rgba(0,0,0,0.04);
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.06), 0 2px 4px -2px rgba(0,0,0,0.04);
  --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.06), 0 4px 6px -4px rgba(0,0,0,0.04);
  --shadow-xl: 0 20px 25px -5px rgba(0,0,0,0.08), 0 8px 10px -6px rgba(0,0,0,0.04);

  /* transitions.dev — card resize */
  --resize-dur: 300ms;
  --resize-ease: cubic-bezier(0.22, 1, 0.36, 1);
  /* transitions.dev — panel reveal */
  --panel-open-dur: 400ms;
  --panel-close-dur: 350ms;
  --panel-translate-x: 100%;
  --panel-blur: 2px;
  --panel-ease: cubic-bezier(0.22, 1, 0.36, 1);
  /* transitions.dev — modal */
  --modal-open-dur: 250ms;
  --modal-close-dur: 150ms;
  --modal-scale: 0.96;
  --modal-scale-close: 0.96;
  --modal-ease: cubic-bezier(0.22, 1, 0.36, 1);
  /* transitions.dev — icon swap */
  --icon-swap-dur: 200ms;
  --icon-swap-blur: 2px;
  --icon-swap-start-scale: 0.25;
  --icon-swap-ease: ease-in-out;
  /* transitions.dev — notification badge */
  --badge-slide-dur: 260ms;
  --badge-pop-dur: 500ms;
  --badge-pop-close-dur: 180ms;
  --badge-fade-dur: 400ms;
  --badge-fade-close-dur: 180ms;
  --badge-blur: 2px;
  --badge-offset-x: -8.2px;
  --badge-offset-y: 12.4px;
  --badge-slide-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --badge-pop-ease: cubic-bezier(0.34, 1.36, 0.64, 1);
  --badge-close-ease: cubic-bezier(0.4, 0, 0.2, 1);
}

*, *::before, *::after { box-sizing: border-box; }

/* ── transitions.dev ── */
.t-resize {
  transition:
    min-width var(--resize-dur) var(--resize-ease),
    max-width var(--resize-dur) var(--resize-ease),
    flex-basis var(--resize-dur) var(--resize-ease),
    box-shadow var(--resize-dur) var(--resize-ease);
  will-change: min-width, max-width, flex-basis;
}
.t-panel-slide {
  transform: translateX(var(--panel-translate-x));
  opacity: 0; filter: blur(var(--panel-blur)); pointer-events: none;
  transition:
    transform var(--panel-close-dur) var(--panel-ease),
    opacity   var(--panel-close-dur) var(--panel-ease),
    filter    var(--panel-close-dur) var(--panel-ease);
  will-change: transform, opacity, filter;
}
.t-panel-slide[data-open="true"] {
  transform: translateX(0); opacity: 1; filter: blur(0); pointer-events: auto;
  transition:
    transform var(--panel-open-dur) var(--panel-ease),
    opacity   var(--panel-open-dur) var(--panel-ease),
    filter    var(--panel-open-dur) var(--panel-ease);
}
.t-modal {
  transform-origin: center;
  transform: scale(var(--modal-scale)); opacity: 0; pointer-events: none;
  transition:
    transform var(--modal-open-dur) var(--modal-ease),
    opacity   var(--modal-open-dur) var(--modal-ease);
  will-change: transform, opacity;
}
.t-modal.is-open { transform: scale(1); opacity: 1; pointer-events: auto; }
.t-modal.is-closing {
  transform: scale(var(--modal-scale-close)); opacity: 0; pointer-events: none;
  transition:
    transform var(--modal-close-dur) var(--modal-ease),
    opacity   var(--modal-close-dur) var(--modal-ease);
}
.t-icon-swap { position: relative; display: inline-grid; place-items: center; }
.t-icon-swap .t-icon {
  grid-area: 1 / 1;
  transition:
    opacity   var(--icon-swap-dur) var(--icon-swap-ease),
    filter    var(--icon-swap-dur) var(--icon-swap-ease),
    transform var(--icon-swap-dur) var(--icon-swap-ease);
  will-change: opacity, filter, transform;
}
.t-icon-swap[data-state="a"] .t-icon[data-icon="a"],
.t-icon-swap[data-state="b"] .t-icon[data-icon="b"] {
  opacity: 1; filter: blur(0); transform: scale(1);
}
.t-icon-swap[data-state="a"] .t-icon[data-icon="b"],
.t-icon-swap[data-state="b"] .t-icon[data-icon="a"] {
  opacity: 0; filter: blur(var(--icon-swap-blur)); transform: scale(var(--icon-swap-start-scale));
}

@media (prefers-reduced-motion: reduce) {
  .t-resize, .t-panel-slide, .drawer-panel, .drawer-overlay, .t-modal, .t-icon-swap .t-icon, .fab-pill { transition: none !important; animation: none !important; }
}

/* ── Body & layout ── */
body {
  margin: 0;
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  background:
    radial-gradient(circle at 10% -20%, #d1fae5 0%, transparent 40%),
    radial-gradient(circle at 90% -20%, #e0e7ff 0%, transparent 42%),
    linear-gradient(180deg, var(--bg-alt), var(--bg) 30%);
}
.app-shell { width: min(1440px, calc(100% - 32px)); margin: 24px auto 48px auto; }

/* ── Typography ── */
h1, h2, h3 { margin: 0; line-height: 1.3; }
h1 { font-size: 26px; font-weight: 800; letter-spacing: -0.025em; }
h2 { font-size: 17px; font-weight: 700; margin-bottom: 12px; letter-spacing: -0.01em; }
h3 { font-size: 14px; font-weight: 700; margin-bottom: 8px; }
.subtitle { color: var(--muted); margin-top: 4px; font-size: 13px; line-height: 1.5; }

/* ── Header ── */
.hero, .toolbar { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; margin-bottom: 16px; }
.hero { margin-bottom: 20px; }

/* ── Cards ── */
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius-xl);
  padding: 20px 24px;
  box-shadow: var(--shadow-sm);
}
.card h2 { margin-top: 0; }

/* ── Rows ── */
.row { display: flex; gap: 12px; flex-wrap: wrap; }
.row > div { flex: 1 1 180px; }

/* ── Forms ── */
label { display: block; font-weight: 600; font-size: 12px; margin-bottom: 4px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.04em; }
input, select, textarea {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 9px 12px;
  font-family: inherit;
  font-size: 14px;
  background: #fff;
  color: var(--text);
  resize: vertical;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(5, 150, 105, 0.12); }
input:disabled, select:disabled { background: var(--gray-100); color: var(--gray-400); }
select { appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; padding-right: 32px; }

/* ── Buttons ── */
button {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 9px 16px;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  background: #fff;
  color: var(--text);
  transition: all 0.15s ease;
}
button:hover { background: var(--gray-50); border-color: var(--gray-300); }
button:active { transform: scale(0.98); }
button.primary { background: var(--accent); color: #fff; border-color: var(--accent); font-weight: 700; }
button.primary:hover { background: var(--accent-dark); border-color: var(--accent-dark); box-shadow: var(--shadow-md); }

.hint { font-size: 12px; margin-top: 4px; color: var(--muted); }
.muted { color: var(--muted); }
.status-msg { margin-top: 10px; font-weight: 600; font-size: 13px; }
.action-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.run-detail-empty { color: var(--muted); text-align: center; padding: 48px 0; font-size: 14px; }

/* ── Drawer ── */
.drawer-overlay {
  position: fixed; inset: 0; background: rgba(15,23,42,0.3); z-index: 999;
  backdrop-filter: blur(2px);
  opacity: 0; pointer-events: none;
  transition: opacity var(--panel-open-dur) var(--panel-ease);
}
.drawer-overlay.open { opacity: 1; pointer-events: auto; }
.drawer-panel {
  position: fixed; top: 0; right: 0; bottom: 0; width: min(700px, 94vw);
  background: var(--bg); z-index: 1000; overflow-y: auto;
  box-shadow: var(--shadow-xl); padding: 24px 28px 48px;
  transform: translateX(100%); opacity: 0; filter: blur(var(--panel-blur)); pointer-events: none;
  transition:
    transform var(--panel-close-dur) var(--panel-ease),
    opacity   var(--panel-close-dur) var(--panel-ease),
    filter    var(--panel-close-dur) var(--panel-ease);
  will-change: transform, opacity, filter;
}
.drawer-panel.open {
  transform: translateX(0); opacity: 1; filter: blur(0); pointer-events: auto;
  transition:
    transform var(--panel-open-dur) var(--panel-ease),
    opacity   var(--panel-open-dur) var(--panel-ease),
    filter    var(--panel-open-dur) var(--panel-ease);
}
.drawer-close {
  position: sticky; top: 12px; float: right; width: 32px; height: 32px;
  border-radius: 50%; border: 1px solid var(--line); background: #fff;
  font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center;
  z-index: 10; color: var(--muted); transition: all 0.15s ease;
}
.drawer-close:hover { background: var(--gray-50); color: var(--text); }

/* ── FAB ── */
.fab-group {
  position: fixed; bottom: 28px; right: 28px; z-index: 998;
  display: flex; align-items: center; gap: 10px;
}
.fab-pill {
  padding: 10px 18px; border-radius: 28px; border: none;
  font-size: 13px; font-weight: 700; cursor: pointer;
  display: flex; align-items: center; gap: 6px;
  box-shadow: var(--shadow-lg);
  opacity: 0; filter: blur(var(--badge-blur)); transform: translateY(6px) scale(0.9); pointer-events: none;
  transition:
    transform var(--badge-pop-close-dur) var(--badge-close-ease),
    opacity   var(--badge-fade-close-dur) var(--badge-close-ease),
    filter    var(--badge-pop-close-dur) var(--badge-close-ease);
  will-change: transform, opacity, filter;
}
.fab-pill.visible {
  opacity: 1; filter: blur(0); transform: translateY(0) scale(1); pointer-events: auto;
  transition:
    transform var(--badge-pop-dur) var(--badge-pop-ease),
    opacity   var(--badge-fade-dur) var(--badge-pop-ease),
    filter    var(--badge-pop-dur) var(--badge-pop-ease);
}
.fab-pill:hover { transform: translateY(-2px) scale(1.02); box-shadow: var(--shadow-xl); }
.fab-pill.advance { background: var(--accent); color: #fff; }
.fab-pill.advance:hover { background: var(--accent-dark); }
.fab-pill.reject { background: #fff; color: var(--danger); border: 1.5px solid var(--danger); }
.fab-pill.reject:hover { background: var(--danger-light); }
.fab-create {
  width: 44px; height: 44px; padding: 0; border-radius: 50%;
  background: var(--accent); color: #fff; border: none;
  font-size: 20px; cursor: pointer;
  box-shadow: var(--shadow-lg);
  display: flex; align-items: center; justify-content: center;
  transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
.fab-create:hover { transform: scale(1.08); box-shadow: var(--shadow-xl); background: var(--accent-dark); }
.fab-create:active { transform: scale(0.95); }

/* ── Accordion ── */
.accordion { border: 1px solid var(--line); border-radius: var(--radius-lg); overflow: hidden; background: #fff; }
.accordion-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px; cursor: pointer; border-bottom: 1px solid var(--line-light);
  font-weight: 600; font-size: 14px; transition: background 0.15s ease;
}
.accordion-header:hover { background: var(--gray-50); }
.accordion-header:last-child { border-bottom: none; }
.accordion-body { padding: 16px 18px; display: none; background: var(--gray-50); }
.accordion-body.open { display: block; }
.accordion-header .chevron { transition: transform 0.2s ease; color: var(--muted); }
.accordion-header.open .chevron { transform: rotate(90deg); }

/* ── Wizard ── */
.wizard-sidebar { width: 160px; }
.wizard-step { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: var(--radius-sm); font-size: 13px; cursor: pointer; transition: all 0.15s ease; }
.wizard-step:hover { background: var(--gray-50); }
.wizard-step.active { background: var(--accent-light); color: var(--accent-dark); font-weight: 600; }
.wizard-step.done { color: var(--accent); }
.wizard-step.pending { color: var(--gray-400); }

/* ── File upload ── */
.file-drop-zone {
  border: 2px dashed var(--gray-300); border-radius: var(--radius-lg); padding: 28px; text-align: center;
  background: var(--gray-50); transition: border-color 0.2s ease, background 0.2s ease; cursor: pointer;
}
.file-drop-zone:hover { border-color: var(--accent); background: var(--accent-light); }
.file-preview-grid { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.file-preview-thumb { width: 64px; height: 64px; border-radius: var(--radius-sm); object-fit: cover; background: var(--gray-200); border: 1px solid var(--line); }
.file-preview-thumb.video { position: relative; }
.file-preview-thumb.video::after { content: "\u25b6"; position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 16px; background: rgba(0,0,0,0.25); border-radius: var(--radius-sm); }

/* ── Misc form elements ── */
.quick-fill-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.spec-row { display: flex; gap: 8px; }
.spec-field { flex: 1; min-width: 80px; }
.template-bar { display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: var(--gray-50); border-radius: var(--radius); margin-bottom: 14px; border: 1px solid var(--line); flex-wrap: wrap; }
.template-bar select { width: auto; min-width: 140px; }
.preset-popover { position: absolute; background: #fff; border: 1px solid var(--line); border-radius: var(--radius-lg); box-shadow: var(--shadow-xl); z-index: 100; min-width: 280px; }
.preset-section-label { font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--gray-400); padding: 8px 14px 2px; letter-spacing: 0.06em; }
.preset-item { padding: 8px 14px; font-size: 13px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-radius: 0; transition: background 0.1s ease; }
.preset-item:hover { background: var(--gray-50); }
.preset-item-actions { display: flex; gap: 4px; opacity: 0; transition: opacity 0.1s ease; }
.preset-item:hover .preset-item-actions { opacity: 1; }
.tab-nav { display: flex; gap: 0; border-bottom: 2px solid var(--line); margin-bottom: 8px; }
.tab-btn { padding: 10px 18px; border: none; background: none; cursor: pointer; font-weight: 600; font-size: 13px; color: var(--muted); border-bottom: 2px solid transparent; margin-bottom: -2px; transition: color 0.15s ease, border-color 0.15s ease; }
.tab-btn:hover { color: var(--text); }
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }

/* ── Tables ── */
.table-wrap { overflow: auto; border-radius: var(--radius-lg); border: 1px solid var(--line); background: #fff; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid var(--line-light); padding: 10px 12px; text-align: left; vertical-align: middle; }
thead th { background: var(--gray-50); font-weight: 700; color: var(--text-secondary); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; white-space: nowrap; }
tr.selected { background: var(--accent-light); }
tr:hover { background: var(--gray-50); }

.runs-panel { display: flex; flex-direction: column; min-height: 0; }
.runs-panel .table-wrap { flex: 1; min-height: 0; overflow: auto; }
.runs-panel table { table-layout: fixed; min-width: 0; }
.runs-actions {
  margin-top: 12px; display:flex; justify-content:center; gap:8px; flex-wrap: wrap;
}
.runs-actions button { min-width: 148px; padding: 11px 20px; font-size: 14px; font-weight: 700; border-radius: var(--radius-sm); }

.status-ok { color: var(--accent); font-weight: 600; }
.status-error { color: var(--danger); font-weight: 600; }

/* ── Status pills ── */
.status-pill {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 999px;
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
  white-space: nowrap;
}
.status-pill:before {
  content: ""; width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
}
.status-pill.running { background: var(--info-light); color: var(--info); }
.status-pill.running:before { background: var(--info); animation: statusPulse 1.4s ease-in-out infinite; }
.status-pill.waiting_review { background: var(--warning-light); color: var(--warning); }
.status-pill.waiting_review:before { background: var(--warning); animation: statusPulse 2.2s ease-in-out infinite; }
.status-pill.completed { background: var(--green-50); color: var(--green-700); }
.status-pill.completed:before { background: var(--green-500); }
.status-pill.failed { background: var(--danger-light); color: var(--danger); }
.status-pill.failed:before { background: var(--danger); }
.status-pill.rejected { background: #fef2f2; color: #b91c1c; }
.status-pill.rejected:before { background: #ef4444; }
.status-pill.draft { background: var(--gray-100); color: var(--gray-500); }
.status-pill.draft:before { background: var(--gray-400); }
@keyframes statusPulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.35; transform: scale(0.65); }
}

/* ── Refresh indicator ── */
.refresh-indicator {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px; color: var(--muted); margin-left: 8px;
}
.refresh-indicator .dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent); opacity: 0.5; transition: opacity 300ms ease;
}
.refresh-indicator.active .dot { opacity: 1; animation: statusPulse 1.6s ease-in-out infinite; }

/* ── Agent trace ── */
.agent-trace {
  display:flex; gap:10px; overflow-x:auto; overflow-y:hidden;
  padding: 4px 0 8px 0; scroll-behavior: smooth; scroll-snap-type: x proximity;
}
.trace-event {
  border:1px solid var(--line); border-radius: var(--radius); padding:10px 12px;
  background: #fff; min-width: 220px; max-width: 280px;
  flex: 0 0 clamp(220px, 22vw, 280px); scroll-snap-align: end;
  box-shadow: var(--shadow-xs);
}
.trace-event.trace-event-expanded {
  min-width: 420px; max-width: 560px;
  flex-basis: clamp(420px, 48vw, 560px);
  box-shadow: var(--shadow-md);
}
.trace-head { display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap; margin-bottom:4px; }
.trace-index {
  min-width: 22px; height: 22px; border-radius: 999px;
  display: inline-flex; align-items: center; justify-content: center;
  padding: 0 6px; font-size: 11px; font-weight: 700;
  color: var(--accent-dark); background: var(--accent-light);
  margin-right: 6px; flex-shrink: 0;
}
.trace-head-main { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
.trace-message {
  font-size:13px; color: var(--text-secondary); line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden;
}
.trace-payload { margin-top: 6px; }
.trace-payload[open] { animation: tracePayloadOpen 180ms ease; }
@keyframes tracePayloadOpen {
  from { opacity: 0; transform: translateY(-2px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── Deliverables ── */
.deliverables { display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:12px; margin-top:12px; }
.deliverable-card {
  border:1px solid var(--line); border-radius: var(--radius-lg); padding:14px;
  background: #fff; min-height: 190px; box-shadow: var(--shadow-xs);
}
.stage-title { font-weight: 700; margin-bottom: 4px; color: var(--accent-dark); }

/* ── Timeline ── */
.timeline {
  margin-top: 12px; max-height: 560px; overflow-y: auto;
  border:1px solid var(--line); border-radius: var(--radius-lg); padding:12px;
  background: #fff;
}
.stage-card {
  border-left: 3px solid var(--accent); padding: 10px 14px;
  margin-bottom: 10px; background: var(--gray-50); border-radius: var(--radius-sm);
}

/* ── Media preview ── */
.img-preview {
  width: 100%; border-radius: var(--radius); border: 1px solid var(--line);
  object-fit: contain; max-height: 520px; background: var(--gray-100);
}
.media-preview {
  width: 100%; border-radius: var(--radius); border: 1px solid var(--line);
  background: var(--gray-100); display:block;
}
.media-preview.image { object-fit: contain; max-height: 520px; }
.media-preview.video { aspect-ratio: 9 / 16; max-height: 520px; object-fit: contain; background: #000; }

/* ── Variant board ── */
.variant-board-header {
  margin-top:14px; display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap;
}
.variant-board-header h3 { margin: 0; }
.variant-toggle-btn { padding: 7px 12px; font-size: 12px; border-radius: 999px; }
.variant-board-body {
  overflow: hidden; max-height: 8000px; opacity: 1; transform: translateY(0);
  transition: max-height 220ms ease, opacity 180ms ease, transform 180ms ease;
}
.variant-board-body.is-collapsed { max-height: 0; opacity: 0; transform: translateY(-4px); }
.variant-scoreboard {
  display: flex; gap: 10px; overflow-x: auto; padding: 8px 2px 12px 2px;
  scroll-behavior: smooth; scroll-snap-type: x proximity;
}
.variant-score-card {
  flex: 0 0 192px;
  border: 1px solid var(--line); border-radius: var(--radius-lg); padding: 14px;
  background: #fff; cursor: pointer; scroll-snap-align: start;
  transition: border-color 150ms ease, box-shadow 150ms ease, transform 120ms ease;
  position: relative; box-shadow: var(--shadow-xs);
}
.variant-score-card:hover { border-color: var(--accent); box-shadow: var(--shadow-md); transform: translateY(-2px); }
.variant-score-card.selected {
  border-color: var(--accent); box-shadow: 0 0 0 3px rgba(5,150,105,0.15);
  background: var(--green-50);
}
.variant-score-card .rank-badge {
  position: absolute; top: -8px; left: -6px;
  width: 28px; height: 28px; border-radius: 50%;
  background: var(--accent); color: #fff;
  font-size: 13px; font-weight: 800;
  display: flex; align-items: center; justify-content: center;
  box-shadow: var(--shadow-md);
}
.variant-score-card .score-number { font-size: 36px; font-weight: 800; line-height: 1; margin: 6px 0 2px 0; }
.variant-score-card .score-number.high { color: var(--accent); }
.variant-score-card .score-number.mid { color: var(--warning); }
.variant-score-card .score-number.low { color: var(--danger); }
.variant-score-card .thumb {
  width: 100%; height: 140px; object-fit: cover;
  border-radius: var(--radius-sm); border: 1px solid var(--line);
  background: var(--gray-100); margin: 8px 0;
}
.variant-score-card .quick-actions { display: flex; gap: 5px; margin-top: 8px; }
.variant-score-card .quick-actions button { flex: 1; padding: 6px 4px; font-size: 11px; border-radius: var(--radius-sm); }
.variant-detail-panel {
  border: 2px solid var(--accent); border-radius: var(--radius-xl); padding: 24px;
  margin-top: 14px; background: #fff;
  transform-origin: top center;
  transform: scale(var(--modal-scale)); opacity: 0; pointer-events: none;
  transition:
    transform var(--modal-open-dur) var(--modal-ease),
    opacity   var(--modal-open-dur) var(--modal-ease);
  will-change: transform, opacity;
}
.variant-detail-panel.open { transform: scale(1); opacity: 1; pointer-events: auto; }
.variant-detail-panel.is-closing {
  transform: scale(var(--modal-scale-close)); opacity: 0; pointer-events: none;
  transition:
    transform var(--modal-close-dur) var(--modal-ease),
    opacity   var(--modal-close-dur) var(--modal-ease);
}
.variant-detail-panel .detail-image {
  max-width: 100%; max-height: 540px; border-radius: var(--radius);
  border: 1px solid var(--line); object-fit: contain; background: var(--gray-100); display: block;
}
.variant-detail-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 20px; align-items: start; }
.variant-score-breakdown { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 12px; }
.variant-score-breakdown .score-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 12px; border-radius: var(--radius-sm);
  background: var(--gray-50); font-size: 13px;
}
.variant-score-breakdown .score-item .bar { flex: 1; height: 5px; border-radius: 3px; margin: 0 8px; background: var(--gray-200); }
.variant-score-breakdown .score-item .bar-fill { height: 100%; border-radius: 3px; background: var(--accent); }
.variant-detail-actions { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
.variant-detail-actions button { padding: 10px 16px; font-size: 13px; font-weight: 700; border-radius: var(--radius-sm); }
.variant-filter-bar {
  display:grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap:8px; align-items:end;
  margin:10px 0; padding:12px; border:1px solid var(--line); border-radius:var(--radius-lg);
  background: var(--gray-50);
}
.quality-row { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
.quality-chip {
  display:inline-flex; align-items:center; border-radius:999px; padding:3px 8px;
  border:1px solid var(--line); background: var(--gray-50); color: var(--text-secondary);
  font-size:11px; font-weight:600;
}
.quality-chip.good { background: var(--green-50); border-color: var(--green-200); color: var(--green-700); }
.quality-chip.warn { background: var(--warning-light); border-color: #fde68a; color: #92400e; }
.quality-chip.bad { background: var(--danger-light); border-color: #fecaca; color: #991b1b; }

/* ── Navigation ── */
.links { display:flex; gap:6px; flex-wrap: wrap; }
a { color: var(--accent-dark); text-decoration: none; transition: color 0.15s ease; }
a:hover { color: var(--accent); }
.nav-link {
  border: 1px solid var(--line); background: #fff;
  padding: 7px 14px; border-radius: 999px;
  font-size: 12px; font-weight: 600; color: var(--text-secondary);
  text-decoration: none; transition: all 0.15s ease;
}
.nav-link:hover { background: var(--gray-50); border-color: var(--gray-300); color: var(--text); text-decoration: none; }
.nav-link.active { background: var(--accent-light); border-color: var(--accent); color: var(--accent-dark); }
.topbar { margin-bottom: 18px; }
.top-actions { display:flex; gap:10px; flex-wrap: wrap; align-items: center; }
.data-source-block {
  display:flex; align-items:center; gap:10px; flex-wrap:wrap;
  padding:8px 12px; background: var(--gray-50); border-radius: var(--radius-sm);
  border:1px solid var(--line); margin-bottom:10px;
}

/* ── Pill ── */
.pill {
  display:inline-block; padding:3px 10px; border-radius:20px;
  font-size:12px; border:1px solid var(--line); background: var(--gray-50);
  margin-right:6px; margin-bottom:4px; color: var(--text-secondary);
}

/* ── Misc ── */
pre {
  white-space: pre-wrap; word-break: break-word;
  border: 1px solid var(--line); border-radius: var(--radius);
  padding: 12px; background: var(--gray-50); font-size: 12px; color: var(--text-secondary);
}
summary { cursor: pointer; font-weight: 600; color: var(--accent-dark); }

/* ── Responsive ── */
@media (max-width: 860px) {
  .app-shell { width: calc(100% - 16px); margin-top: 12px; }
  .deliverables { grid-template-columns: 1fr; }
  .variant-score-card { flex: 0 0 156px; }
  .variant-score-card .thumb { height: 110px; }
  .variant-detail-grid { grid-template-columns: 1fr; }
  .variant-filter-bar { grid-template-columns: 1fr; }
  .hero { flex-direction: column; align-items: flex-start; }
  .trace-event { min-width: min(86vw, 320px); flex-basis: min(86vw, 320px); }
  .trace-event.trace-event-expanded { min-width: min(94vw, 640px); flex-basis: min(94vw, 640px); }
  .runs-actions { justify-content: stretch; }
  .runs-actions button { flex: 1 1 48%; min-width: 136px; padding: 11px 16px; font-size: 14px; }
}
"""


def render_head(title: str = "Crispy Dashboard") -> str:
    return f"""<html>
  <head>
    <title>{title}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>{SHARED_STYLES}</style>
  </head>"""


def render_shell_top() -> str:
    return """  <body>
    <div class="app-shell">
      <header class="hero">
        <div>
          <h1>Crispy Dashboard</h1>
          <div class="subtitle">Production MVP control plane for multimodal creative generation and review.</div>
          <div class="subtitle">Flow: input product/task -> GM intake summary -> planning with product+industry memory -> divergence -> copy/image & video generation -> evaluation winner -> feedback updates GM memory.</div>
        </div>
      </header>
      <div class="topbar">
        <div class="top-actions links">
          <a class="nav-link" href="/dashboard/agent-apis">API &amp; Integration Configs</a>
          <a class="nav-link" href="/dashboard/shop-analysis">Shop Analysis</a>
          <a class="nav-link" href="/dashboard/data">Data Dashboard</a>
          <a class="nav-link" href="/dashboard/calendar">Content Calendar</a>
          <a class="nav-link" href="/dashboard/assets">Asset Library</a>
          <a class="nav-link" href="/dashboard/personas">Personas</a>
          <button class="nav-link" onclick="backupDatabase()" title="Back up the database to backups/">Backup DB</button>
        </div>
      </div>
      <div style="display:flex;gap:20px;flex-wrap:wrap;">
        <div style="flex:0 0 480px;min-width:0;">
          <section class="card runs-panel" style="position:sticky;top:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
              <h2 style="margin-bottom:0;display:flex;align-items:center;gap:6px;">Runs <span class="refresh-indicator active" id="runs-refresh-indicator" title="Auto-refreshing every 5s"><span class="dot"></span> live</span></h2>
              <button onclick="refreshRuns()" style="font-size:12px;padding:6px 10px;">Refresh</button>
            </div>
            <div class="data-source-block">
              <label style="margin-bottom:0;white-space:nowrap;">Shop</label>
              <select id="data-source-select" onchange="switchDataSource()" style="width:auto;min-width:160px;font-size:12px;padding:5px 8px;"></select>
              <div id="data-source-path" class="muted mono" style="font-size:11px;"></div>
            </div>
            <div class="table-wrap">
              <table>
                <thead><tr><th style="width:18%">Run ID</th><th style="width:34%">Status</th><th style="width:18%">Mode</th><th style="width:30%">Updated</th></tr></thead>
                <tbody id="runs-body"></tbody>
              </table>
            </div>
          </section>
        </div>
        <div style="flex:1 1 480px;min-width:0;">"""


def render_shell_bottom() -> str:
    return """        </div>
      </div>
    </div>"""


def render_dashboard(create_run_html: str, shared_js: str) -> str:
    drawer = f"""  <div class="drawer-overlay" id="drawer-overlay" onclick="closeDrawer()"></div>
  <div class="drawer-panel" id="drawer-panel">
    <button class="drawer-close" onclick="closeDrawer()" title="Close">&times;</button>
    <h2 style="margin-bottom:14px;">Create Run</h2>
{create_run_html}
    <div id="create-msg" class="status-msg muted"></div>
  </div>
  <div class="fab-group">
    <button class="fab-pill advance" id="fab-advance" onclick="advanceRun()" title="Advance to next stage">&#9654; Advance</button>
    <button class="fab-pill reject" id="fab-reject" onclick="rejectRun()" title="Reject current stage">&#10005; Reject</button>
    <button class="fab-create" id="fab-create" onclick="toggleFabCreate()" title="Create Run">
      <span class="t-icon-swap" id="fab-icon-swap" data-state="a">
        <span class="t-icon" data-icon="a">+</span>
        <span class="t-icon" data-icon="b">&times;</span>
      </span>
    </button>
  </div>"""

    run_detail_html = """          <section class="card">
            <h2>Run Detail</h2>
            <div id="run-detail" class="run-detail-empty">Select a run.</div>
          </section>"""

    return (
        render_head()
        + render_shell_top()
        + run_detail_html
        + render_shell_bottom()
        + drawer
        + shared_js
        + "\n  </body>\n</html>"
    )
