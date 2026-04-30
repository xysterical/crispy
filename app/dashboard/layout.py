# app/dashboard/layout.py

from __future__ import annotations


SHARED_STYLES = """
:root {
  --bg: #f4f7f2;
  --bg-alt: #e9f1f7;
  --card: rgba(255, 255, 255, 0.9);
  --text: #173027;
  --muted: #5d6f66;
  --line: #d9e4dc;
  --accent: #1f7a62;
  --accent-dark: #145746;
  --soft: #edf5f0;
  --danger: #be3b3b;
  --radius: 16px;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  background:
    radial-gradient(circle at 10% -20%, #d9ede6 0%, transparent 40%),
    radial-gradient(circle at 90% -20%, #d8e9f6 0%, transparent 42%),
    linear-gradient(180deg, var(--bg-alt), var(--bg) 30%);
}
.app-shell { width: min(1460px, calc(100% - 24px)); margin: 22px auto 36px auto; }
.hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; margin-bottom: 14px; }
h1, h2, h3 { margin: 0; line-height: 1.25; }
h1 { font-size: 28px; letter-spacing: -0.02em; }
h2 { font-size: 20px; margin-bottom: 10px; }
h3 { font-size: 15px; margin-bottom: 8px; }
.subtitle { color: var(--muted); margin-top: 6px; font-size: 14px; }
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 20px 22px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.04);
}
.card h2 { margin-top: 0; }
.row { display: flex; gap: 14px; flex-wrap: wrap; }
.row > div { flex: 1 1 180px; }
label { display: block; font-weight: 600; font-size: 13px; margin-bottom: 3px; color: var(--text); }
input, select, textarea {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  font-family: inherit;
  font-size: 14px;
  background: #fff;
  color: var(--text);
  resize: vertical;
}
input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(31, 122, 98, 0.15); }
input:disabled, select:disabled { background: #f3f4f6; color: #9ca3af; }
button {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 18px;
  font-family: inherit;
  font-size: 14px;
  cursor: pointer;
  background: #fff;
  color: var(--text);
  font-weight: 600;
  transition: background 0.15s;
}
button:hover { background: var(--soft); }
button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
button.primary:hover { background: var(--accent-dark); }
.hint { font-size: 12px; margin-top: 4px; }
.muted { color: var(--muted); }
.status-msg { margin-top: 10px; font-weight: 600; }
.action-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.run-detail-empty { color: var(--muted); text-align: center; padding: 32px 0; }

/* drawer */
.drawer-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.25); z-index: 999;
  opacity: 0; pointer-events: none; transition: opacity 0.25s;
}
.drawer-overlay.open { opacity: 1; pointer-events: auto; }
.drawer-panel {
  position: fixed; top: 0; right: 0; bottom: 0; width: min(700px, 94vw);
  background: var(--bg); z-index: 1000; overflow-y: auto;
  transform: translateX(100%); transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: -4px 0 28px rgba(0,0,0,0.12); padding: 20px 24px 40px;
}
.drawer-panel.open { transform: translateX(0); }
.drawer-close {
  position: sticky; top: 12px; float: right; width: 36px; height: 36px;
  border-radius: 50%; border: 1px solid var(--line); background: #fff;
  font-size: 18px; cursor: pointer; display: flex; align-items: center; justify-content: center;
  z-index: 10;
}
.fab-group {
  position: fixed; bottom: 28px; right: 28px; z-index: 998;
  display: flex; align-items: center; gap: 10px;
}
.fab-pill {
  padding: 10px 18px; border-radius: 28px; border: none;
  font-size: 13px; font-weight: 700; cursor: pointer;
  display: flex; align-items: center; gap: 6px;
  box-shadow: 0 3px 12px rgba(0,0,0,0.12);
  transition: transform 0.15s, box-shadow 0.15s, opacity 0.2s;
  opacity: 0; transform: scale(0.9); pointer-events: none;
}
.fab-pill.visible { opacity: 1; transform: scale(1); pointer-events: auto; }
.fab-pill:hover { transform: translateY(-1px); box-shadow: 0 5px 16px rgba(0,0,0,0.18); }
.fab-pill.advance { background: var(--accent); color: #fff; }
.fab-pill.reject { background: #fff; color: var(--danger); border: 1.5px solid var(--danger); }
.fab-create {
  width: 40px; height: 40px; border-radius: 50%;
  background: #fff; color: var(--accent); border: 1.5px solid var(--accent);
  font-size: 18px; cursor: pointer;
  box-shadow: 0 4px 16px rgba(31, 122, 98, 0.18);
  display: flex; align-items: center; justify-content: center;
  transition: transform 0.15s, box-shadow 0.15s;
}
.fab-create:hover { transform: scale(1.06); box-shadow: 0 6px 20px rgba(31, 122, 98, 0.28); }

/* accordion / wizard specific */
.accordion { border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
.accordion-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px; cursor: pointer; background: #fff; border-bottom: 1px solid var(--line);
  font-weight: 600; font-size: 14px;
}
.accordion-header:hover { background: var(--soft); }
.accordion-header:last-child { border-bottom: none; }
.accordion-body { padding: 16px 18px; display: none; background: #fafbfa; }
.accordion-body.open { display: block; }
.accordion-header .chevron { transition: transform 0.2s; }
.accordion-header.open .chevron { transform: rotate(90deg); }

.wizard-sidebar { width: 160px; }
.wizard-step { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 8px; font-size: 13px; cursor: pointer; }
.wizard-step.active { background: #e0f2fe; color: #2563eb; font-weight: 600; }
.wizard-step.done { color: #059669; }
.wizard-step.pending { color: #9ca3af; }

.file-drop-zone {
  border: 2px dashed var(--line); border-radius: 12px; padding: 24px; text-align: center;
  background: #fafbfa; transition: border-color 0.2s;
}
.file-drop-zone:hover { border-color: var(--accent); }
.file-preview-grid { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.file-preview-thumb { width: 60px; height: 60px; border-radius: 8px; object-fit: cover; background: #e5e7eb; }
.file-preview-thumb.video { position: relative; }
.file-preview-thumb.video::after { content: "\u25b6"; position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 16px; background: rgba(0,0,0,0.2); border-radius: 8px; }

.quick-fill-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.spec-row { display: flex; gap: 8px; }
.spec-field { flex: 1; min-width: 80px; }
.template-bar { display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: #f9fafb; border-radius: var(--radius); margin-bottom: 14px; border: 1px solid var(--line); flex-wrap: wrap; }
.template-bar select { width: auto; min-width: 140px; }
.preset-popover { position: absolute; background: #fff; border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.1); z-index: 100; min-width: 280px; }
.preset-section-label { font-size: 10px; font-weight: 700; text-transform: uppercase; color: #9ca3af; padding: 8px 14px 2px; }
.preset-item { padding: 6px 14px; font-size: 13px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
.preset-item:hover { background: var(--soft); }
.preset-item-actions { display: flex; gap: 4px; visibility: hidden; }
.preset-item:hover .preset-item-actions { visibility: visible; }
.tab-nav { display: flex; gap: 0; border-bottom: 2px solid var(--line); margin-bottom: 4px; }
.tab-btn { padding: 8px 16px; border: none; background: none; cursor: pointer; font-weight: 600; font-size: 13px; color: var(--muted); border-bottom: 2px solid transparent; margin-bottom: -2px; }
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }

/* runs table (shared JS compatibility) */
.table-wrap { overflow: auto; border-radius: 12px; border: 1px solid var(--line); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid #e8eee8; padding: 9px 10px; text-align: left; vertical-align: top; }
thead th { background: #f8fbf8; font-weight: 700; color: #295345; }
tr.selected { background: #eef8f2; }
tr:hover { background: #f8fcfa; }

.runs-panel { display: flex; flex-direction: column; min-height: 0; }
.runs-panel .table-wrap { flex: 1; min-height: 0; overflow: auto; }
.runs-panel table { table-layout: fixed; min-width: 0; }
.runs-actions {
  margin-top: 10px;
  display:flex;
  justify-content:center;
  gap:8px;
  flex-wrap: wrap;
}
.runs-actions button {
  min-width: 148px;
  padding: 10px 16px;
  font-size: 14px;
  font-weight: 700;
}

.status-ok { color: #1f7a62; }
.status-error { color: var(--danger); }

/* status pills */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.status-pill:before {
  content: "";
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-pill.running {
  background: #e3f0fe;
  border: 1px solid #b3d6fc;
  color: #1e5a9e;
}
.status-pill.running:before {
  background: #2b7bd6;
  animation: statusPulse 1.4s ease-in-out infinite;
}
.status-pill.waiting_review {
  background: #fff7e6;
  border: 1px solid #f0cf85;
  color: #8a5d1c;
}
.status-pill.waiting_review:before {
  background: #e8a82a;
  animation: statusPulse 2.2s ease-in-out infinite;
}
.status-pill.completed {
  background: #eaf7ee;
  border: 1px solid #bde0c8;
  color: #21633d;
}
.status-pill.completed:before { background: #2d9d5f; }
.status-pill.failed {
  background: #fdeeee;
  border: 1px solid #efc2c2;
  color: #8a2d2d;
}
.status-pill.failed:before { background: #d94a4a; }
.status-pill.rejected {
  background: #fdf0ee;
  border: 1px solid #efc8c2;
  color: #8a2d2d;
}
.status-pill.rejected:before { background: #d96a4a; }
.status-pill.draft {
  background: #f2f4f5;
  border: 1px solid #d0d5d8;
  color: #5c6b73;
}
.status-pill.draft:before { background: #8e9ba6; }
@keyframes statusPulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.7); }
}

.refresh-indicator {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--muted);
  margin-left: 8px;
}
.refresh-indicator .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.5;
  transition: opacity 300ms ease;
}
.refresh-indicator.active .dot { opacity: 1; animation: statusPulse 1.6s ease-in-out infinite; }

/* agent trace */
.agent-trace {
  display:flex;
  gap:10px;
  overflow-x:auto;
  overflow-y:hidden;
  padding: 4px 0 6px 0;
  scroll-behavior: smooth;
  scroll-snap-type: x proximity;
}
.trace-event {
  border:1px solid #dce7e1;
  border-radius:10px;
  padding:9px;
  background:#fbfdfb;
  min-width: 220px;
  max-width: 280px;
  flex: 0 0 clamp(220px, 22vw, 280px);
  scroll-snap-align: end;
  transition: min-width 200ms ease, max-width 200ms ease, flex-basis 200ms ease, box-shadow 180ms ease;
}
.trace-event.trace-event-expanded {
  min-width: 420px;
  max-width: 560px;
  flex-basis: clamp(420px, 48vw, 560px);
  box-shadow: 0 8px 18px rgba(28, 68, 52, 0.12);
}
.trace-head {
  display:flex;
  justify-content:space-between;
  gap:8px;
  flex-wrap:wrap;
  margin-bottom:4px;
}
.trace-index {
  min-width: 20px;
  height: 20px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 6px;
  font-size: 11px;
  font-weight: 700;
  color: #1c4a3b;
  border: 1px solid #b8d8c8;
  background: linear-gradient(135deg, #eef9f2, #def1e6);
  margin-right: 6px;
  flex-shrink: 0;
}
.trace-head-main {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.trace-message {
  font-size:13px;
  color:#2a3f36;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.trace-payload {
  margin-top: 6px;
}
.trace-payload[open] {
  animation: tracePayloadOpen 180ms ease;
}
@keyframes tracePayloadOpen {
  from { opacity: 0; transform: translateY(-2px); }
  to { opacity: 1; transform: translateY(0); }
}

/* deliverables */
.deliverables { display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:10px; margin-top:10px; }
.deliverable-card {
  border:1px solid #deebe2;
  border-radius:12px;
  padding:11px;
  background:#fdfefe;
  min-height: 190px;
}
.stage-title { font-weight: 700; margin-bottom: 4px; color: #1f463a; }

/* timeline */
.timeline {
  margin-top: 12px;
  max-height: 560px;
  overflow-y: auto;
  border:1px solid #dfeadf;
  border-radius:12px;
  padding:10px;
  background:#fcfffd;
}
.stage-card {
  border-left: 3px solid #8dbda8;
  padding: 8px 10px;
  margin-bottom: 10px;
  background:#f7fcf8;
  border-radius: 8px;
}

/* media preview */
.img-preview {
  width: 100%;
  border-radius: 10px;
  border: 1px solid #dce7e1;
  object-fit: contain;
  max-height: 520px;
  background:#f2f5fa;
}
.media-preview {
  width: 100%;
  border-radius: 10px;
  border: 1px solid #dce7e1;
  background:#f2f5fa;
  display:block;
}
.media-preview.image {
  object-fit: contain;
  max-height: 520px;
}
.media-preview.video {
  aspect-ratio: 9 / 16;
  max-height: 520px;
  object-fit: contain;
  background:#050807;
}

/* variant board */
.variant-board-header {
  margin-top:14px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  flex-wrap:wrap;
}
.variant-board-header h3 { margin: 0; }
.variant-toggle-btn {
  padding: 7px 10px;
  font-size: 12px;
  border-radius: 999px;
}
.variant-board-body {
  overflow: hidden;
  max-height: 8000px;
  opacity: 1;
  transform: translateY(0);
  transition: max-height 220ms ease, opacity 180ms ease, transform 180ms ease;
}
.variant-board-body.is-collapsed {
  max-height: 0;
  opacity: 0;
  transform: translateY(-4px);
}
.variant-scoreboard {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding: 8px 2px 12px 2px;
  scroll-behavior: smooth;
  scroll-snap-type: x proximity;
}
.variant-score-card {
  flex: 0 0 188px;
  border: 1px solid #dce7e1;
  border-radius: 14px;
  padding: 12px;
  background: #fdfefe;
  cursor: pointer;
  scroll-snap-align: start;
  transition: border-color 150ms ease, box-shadow 150ms ease, transform 120ms ease;
  position: relative;
}
.variant-score-card:hover {
  border-color: #b3cfbf;
  box-shadow: 0 4px 14px rgba(28, 68, 52, 0.1);
  transform: translateY(-2px);
}
.variant-score-card.selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(31, 122, 98, 0.18);
  background: #f6fdf9;
}
.variant-score-card .rank-badge {
  position: absolute;
  top: -8px;
  left: -6px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #2d9d79, #1f7a62);
  color: #fff;
  font-size: 13px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(31, 122, 98, 0.28);
}
.variant-score-card .score-number {
  font-size: 36px;
  font-weight: 800;
  line-height: 1;
  margin: 6px 0 2px 0;
}
.variant-score-card .score-number.high { color: #1f7a62; }
.variant-score-card .score-number.mid { color: #b8860b; }
.variant-score-card .score-number.low { color: #b5453a; }
.variant-score-card .thumb {
  width: 100%;
  height: 140px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid #e8eee8;
  background: #f3f5f8;
  margin: 6px 0;
}
.variant-score-card .quick-actions {
  display: flex;
  gap: 5px;
  margin-top: 6px;
}
.variant-score-card .quick-actions button {
  flex: 1;
  padding: 5px 6px;
  font-size: 11px;
  border-radius: 8px;
}
.variant-detail-panel {
  border: 2px solid var(--accent);
  border-radius: 16px;
  padding: 20px;
  margin-top: 14px;
  background: #fafdfb;
  display: none;
  animation: detailSlideIn 200ms ease;
}
.variant-detail-panel.open { display: block; }
@keyframes detailSlideIn {
  from { opacity: 0; transform: translateY(-6px); }
  to { opacity: 1; transform: translateY(0); }
}
.variant-detail-panel .detail-image {
  max-width: 100%;
  max-height: 540px;
  border-radius: 12px;
  border: 1px solid #dce7e1;
  object-fit: contain;
  background: #f3f5f8;
  display: block;
}
.variant-detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.variant-score-breakdown {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  margin-top: 10px;
}
.variant-score-breakdown .score-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  border-radius: 8px;
  background: #f4f8f5;
  font-size: 13px;
}
.variant-score-breakdown .score-item .bar {
  flex: 1;
  height: 5px;
  border-radius: 3px;
  margin: 0 8px;
  background: #dce7e1;
}
.variant-score-breakdown .score-item .bar-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--accent);
}
.variant-detail-actions {
  display: flex;
  gap: 8px;
  margin-top: 14px;
  flex-wrap: wrap;
}
.variant-detail-actions button {
  padding: 10px 14px;
  font-size: 13px;
  font-weight: 700;
}
.variant-filter-bar {
  display:grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap:8px;
  align-items:end;
  margin:10px 0;
  padding:10px;
  border:1px solid #dce7e1;
  border-radius:10px;
  background:#f8fbf9;
}
.quality-row {
  display:flex;
  gap:6px;
  flex-wrap:wrap;
  margin-top:8px;
}
.quality-chip {
  display:inline-flex;
  align-items:center;
  border-radius:999px;
  padding:3px 7px;
  border:1px solid #d5e4dc;
  background:#f4f8f5;
  color:#315a4b;
  font-size:11px;
  font-weight:600;
}
.quality-chip.good { background:#eaf7ee; border-color:#bde0c8; color:#21633d; }
.quality-chip.warn { background:#fff7e6; border-color:#ead19d; color:#735418; }
.quality-chip.bad { background:#fdeeee; border-color:#efc2c2; color:#8a2d2d; }

/* nav links */
.links { display:flex; gap:10px; flex-wrap: wrap; }
a { color: var(--accent-dark); text-decoration: none; }
a:hover { text-decoration: underline; }
.nav-link {
  border: 1px solid var(--line);
  background: #fff;
  padding: 8px 12px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
}
.topbar { margin-bottom: 14px; }
.top-actions { display:flex; gap:10px; flex-wrap: wrap; align-items: center; }
.data-source-block { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }

/* pill (used in timeline, trace, run detail) */
.pill {
  display:inline-block;
  padding:2px 8px;
  border-radius:20px;
  font-size:12px;
  border:1px solid #c9ddd1;
  background: #f7fcf8;
  margin-right:6px;
  margin-bottom:4px;
}

/* misc */
pre {
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid #d8e4db;
  border-radius: 10px;
  padding: 10px;
  background: #f7faf8;
  font-size: 12px;
}
summary { cursor: pointer; font-weight: 600; color: #2a5b4a; }

@media (max-width: 860px) {
  .app-shell { width: calc(100% - 12px); margin-top: 10px; }
  .deliverables { grid-template-columns: 1fr; }
  .variant-score-card { flex: 0 0 156px; }
  .variant-score-card .thumb { height: 110px; }
  .variant-detail-grid { grid-template-columns: 1fr; }
  .variant-filter-bar { grid-template-columns: 1fr; }
  .hero { flex-direction: column; align-items: flex-start; }
  .trace-event {
    min-width: min(86vw, 320px);
    flex-basis: min(86vw, 320px);
  }
  .trace-event.trace-event-expanded {
    min-width: min(94vw, 640px);
    flex-basis: min(94vw, 640px);
  }
  .runs-actions { justify-content: stretch; }
  .runs-actions button {
    flex: 1 1 48%;
    min-width: 136px;
    padding: 11px 16px;
    font-size: 14px;
  }
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
          <a class="nav-link" href="/dashboard/assets">Asset Library</a>
          <a class="nav-link" href="/dashboard/personas">Personas</a>
        </div>
      </div>
      <div style="display:flex;gap:20px;flex-wrap:wrap;">
        <div style="flex:0 0 480px;min-width:0;">
          <section class="card runs-panel" style="position:sticky;top:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
              <h2 style="margin-bottom:0;display:flex;align-items:center;gap:6px;">Runs <span class="refresh-indicator active" id="runs-refresh-indicator" title="Auto-refreshing every 5s"><span class="dot"></span> live</span></h2>
              <button onclick="refreshRuns()" style="font-size:12px;padding:6px 10px;">Refresh</button>
            </div>
            <div class="data-source-block" style="margin-bottom:10px;padding:8px 12px;background:#f8fbf9;border-radius:10px;border:1px solid var(--line);display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
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
    <button class="fab-create" id="fab-create" onclick="openDrawer()" title="Create Run">+</button>
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
