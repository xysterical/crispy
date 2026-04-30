from __future__ import annotations

CALENDAR_PAGE_HTML = """
<div class="calendar-page">
  <div class="calendar-header">
    <div class="calendar-nav">
      <button onclick="calendarPrevWeek()" title="Previous week">&larr;</button>
      <button onclick="calendarToday()" title="Today">Today</button>
      <button onclick="calendarNextWeek()" title="Next week">&rarr;</button>
      <h2 id="calendar-week-label" style="margin:0 12px;font-size:18px;"></h2>
    </div>
    <div class="calendar-actions">
      <select id="calendar-workspace-select" onchange="loadCalendarData()" style="width:auto;min-width:140px;">
        <option value="">Loading...</option>
      </select>
      <select id="calendar-channel-filter" onchange="renderCalendarWeek()" style="width:auto;min-width:130px;">
        <option value="">All Channels</option>
        <option value="meta">Meta Ads</option>
        <option value="tiktok">TikTok</option>
        <option value="youtube">YouTube</option>
        <option value="google">Google Ads</option>
        <option value="amazon">Amazon</option>
      </select>
      <span id="notion-badge" class="notion-badge" title="Notion sync status"></span>
    </div>
  </div>

  <div id="calendar-week-grid" class="calendar-week-grid"></div>

  <div id="schedule-modal" class="t-modal schedule-modal">
    <div class="schedule-modal-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
        <h3 id="schedule-modal-title">New Schedule</h3>
        <button onclick="closeScheduleModal()" style="width:32px;height:32px;border-radius:50%;padding:0;font-size:16px;">&times;</button>
      </div>
      <div class="row">
        <div style="flex:2;"><label>Title</label><input id="sched-title" placeholder="e.g. Summer Sale Creative A" /></div>
        <div style="flex:1;"><label>Channel</label><select id="sched-channel">
          <option value="meta">Meta Ads</option>
          <option value="tiktok">TikTok</option>
          <option value="youtube">YouTube</option>
          <option value="google">Google Ads</option>
          <option value="amazon">Amazon</option>
        </select></div>
      </div>
      <div class="row" style="margin-top:10px;">
        <div style="flex:1;"><label>Date</label><input id="sched-date" type="date" /></div>
        <div style="flex:1;"><label>Time (optional)</label><input id="sched-time" type="time" /></div>
        <div style="flex:1;"><label>Status</label><select id="sched-state">
          <option value="draft">Draft</option>
          <option value="scheduled" selected>Scheduled</option>
          <option value="published">Published</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select></div>
      </div>
      <div class="row" style="margin-top:10px;">
        <div style="flex:2;"><label>Link Variant (optional)</label><select id="sched-variant"><option value="">-- none --</option></select></div>
      </div>
      <div style="margin-top:10px;"><label>Notes</label><textarea id="sched-notes" rows="2" placeholder="Optional notes..."></textarea></div>
      <input type="hidden" id="sched-id" />
      <div class="variant-detail-actions" style="margin-top:14px;">
        <button class="primary" onclick="saveSchedule()">Save</button>
        <button id="sched-delete-btn" onclick="deleteSchedule()" style="color:var(--danger);display:none;">Delete</button>
        <button onclick="closeScheduleModal()">Cancel</button>
      </div>
      <div id="sched-msg" class="status-msg muted" style="margin-top:8px;"></div>
    </div>
  </div>
  <div class="drawer-overlay" id="schedule-overlay" onclick="closeScheduleModal()"></div>
</div>

<style>
.calendar-page { position:relative; }
.calendar-header {
  display:flex; justify-content:space-between; align-items:center;
  flex-wrap:wrap; gap:10px; margin-bottom:16px;
}
.calendar-nav { display:flex; align-items:center; gap:6px; }
.calendar-actions { display:flex; align-items:center; gap:10px; }

.calendar-week-grid {
  display:grid;
  grid-template-columns: repeat(7, 1fr);
  gap:8px;
}
.calendar-day-col {
  background:var(--card);
  border:1px solid var(--line);
  border-radius:12px;
  min-height:160px;
  padding:10px;
  display:flex;
  flex-direction:column;
  gap:6px;
}
.calendar-day-col.today {
  border-color:var(--accent);
  box-shadow:0 0 0 2px rgba(31,122,98,0.12);
}
.calendar-day-header {
  font-weight:700; font-size:13px;
  display:flex; justify-content:space-between; align-items:center;
}
.calendar-day-header .date-num { font-size:18px; }
.calendar-day-col.today .calendar-day-header { color:var(--accent); }

.schedule-card {
  border:1px solid var(--line);
  border-radius:8px; padding:7px 9px;
  background:#fff; font-size:12px;
  cursor:pointer;
  transition: border-color 120ms ease, box-shadow 120ms ease;
  position:relative;
}
.schedule-card:hover {
  border-color:var(--accent);
  box-shadow:0 2px 8px rgba(31,122,98,0.08);
}
.schedule-card .card-title {
  font-weight:600; font-size:13px; margin-bottom:2px;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
.schedule-card .card-meta {
  display:flex; gap:6px; align-items:center;
  color:var(--muted); font-size:11px;
}
.channel-dot {
  width:8px; height:8px; border-radius:50%; flex-shrink:0;
}
.channel-dot.meta { background:#1877F2; }
.channel-dot.tiktok { background:#000; }
.channel-dot.youtube { background:#FF0000; }
.channel-dot.google { background:#4285F4; }
.channel-dot.amazon { background:#FF9900; }

.schedule-modal {
  position:fixed; inset:0; z-index:1001;
  display:flex; align-items:center; justify-content:center;
}
.schedule-modal-card {
  background:var(--bg);
  border-radius:var(--radius);
  padding:20px 24px;
  width:min(560px,94vw);
  max-height:90vh; overflow-y:auto;
  box-shadow:0 12px 40px rgba(0,0,0,0.15);
}
#schedule-overlay {
  position:fixed; inset:0; background:rgba(0,0,0,0.25); z-index:1000;
  opacity:0; pointer-events:none;
  transition:opacity var(--modal-open-dur) var(--modal-ease);
}
#schedule-overlay.open { opacity:1; pointer-events:auto; }

.notion-badge {
  font-size:11px; padding:3px 8px; border-radius:999px;
  font-weight:600;
}
.notion-badge.connected { background:#eaf7ee; color:#21633d; border:1px solid #bde0c8; }
.notion-badge.disconnected { background:#fdeeee; color:#8a2d2d; border:1px solid #efc2c2; }

.add-schedule-btn {
  width:100%; padding:6px; border:1px dashed var(--line); border-radius:8px;
  background:transparent; color:var(--muted); font-size:12px; cursor:pointer;
  transition:border-color 120ms, color 120ms;
}
.add-schedule-btn:hover { border-color:var(--accent); color:var(--accent); }

@media (max-width:860px) {
  .calendar-week-grid { grid-template-columns:1fr; }
  .schedule-modal-card { width:96vw; padding:14px; }
}
</style>

<script>
(function(){
  const today = new Date();
  let calendarWeekStart = new Date(today);
  calendarWeekStart.setDate(today.getDate() - ((today.getDay() + 6) % 7));
  window.__calendarWorkspaces = [];

  async function loadCalendarWorkspaces(){
    try {
      const r = await fetch('/shops?limit=50');
      const data = await r.json();
      window.__calendarWorkspaces = data.shops || data.items || [];
      const sel = document.getElementById('calendar-workspace-select');
      if(!sel) return;
      sel.innerHTML = window.__calendarWorkspaces.map(function(w){
        return '<option value="' + w.id + '">' + escHtml(w.name) + '</option>';
      }).join('');
      if(window.__calendarWorkspaces.length > 0){
        sel.value = window.__calendarWorkspaces[0].id;
      }
    } catch(e){
      const sel = document.getElementById('calendar-workspace-select');
      if(sel) sel.innerHTML = '<option value="workspace_demo">workspace_demo</option>';
    }
  }

  function getCalendarWorkspaceId(){
    const sel = document.getElementById('calendar-workspace-select');
    if(sel && sel.value) return sel.value;
    if(window.__calendarWorkspaces && window.__calendarWorkspaces.length > 0){
      return window.__calendarWorkspaces[0].id;
    }
    return 'workspace_demo';
  }

  function getCalendarProjectId(){
    return getCalendarWorkspaceId() + '_project';
  }

  window.calendarPrevWeek = function(){
    calendarWeekStart.setDate(calendarWeekStart.getDate() - 7);
    loadCalendarData();
  };
  window.calendarNextWeek = function(){
    calendarWeekStart.setDate(calendarWeekStart.getDate() + 7);
    loadCalendarData();
  };
  window.calendarToday = function(){
    calendarWeekStart = new Date(today);
    calendarWeekStart.setDate(today.getDate() - ((today.getDay() + 6) % 7));
    loadCalendarData();
  };

  function fmtDate(d){ return d.toISOString().slice(0,10); }

  function getWeekDates(){
    const dates = [];
    for(let i=0;i<7;i++){
      const d = new Date(calendarWeekStart);
      d.setDate(d.getDate()+i);
      dates.push(d);
    }
    return dates;
  }

  async function checkNotionStatus(){
    try {
      const r = await fetch('/content-schedules/notion-status');
      const data = await r.json();
      const badge = document.getElementById('notion-badge');
      if(!badge) return;
      if(data.ok){
        badge.textContent = 'Notion Connected';
        badge.className = 'notion-badge connected';
      } else {
        badge.textContent = 'Notion: ' + (data.error || 'Not configured');
        badge.className = 'notion-badge disconnected';
      }
    } catch(e){}
  }

  window.loadCalendarData = async function(){
    const dates = getWeekDates();
    const start = fmtDate(dates[0]);
    const end = fmtDate(dates[6]);
    document.getElementById('calendar-week-label').textContent =
      dates[0].toLocaleDateString('en-US',{month:'short',day:'numeric'}) + ' \\u2013 ' +
      dates[6].toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'});

    const wsId = getCalendarWorkspaceId();

    try {
      const r = await fetch('/content-schedules?workspace_id=' + encodeURIComponent(wsId) +
        '&start_date=' + start + '&end_date=' + end);
      const data = await r.json();
      window.__currentSchedules = data.items || [];
    } catch(e){
      window.__currentSchedules = [];
    }
    renderCalendarWeek();
    checkNotionStatus();
  };

  function groupByDate(schedules){
    const map = {};
    schedules.forEach(function(s){
      const d = s.scheduled_date;
      if(!map[d]) map[d] = [];
      map[d].push(s);
    });
    return map;
  }

  window.renderCalendarWeek = function(){
    const dates = getWeekDates();
    const grouped = groupByDate(window.__currentSchedules || []);
    const channelFilter = document.getElementById('calendar-channel-filter')?.value || '';
    const dayNames = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
    let html = '';
    dates.forEach(function(d,i){
      const key = fmtDate(d);
      const items = grouped[key] || [];
      const filtered = channelFilter ? items.filter(function(s){return s.channel===channelFilter;}) : items;
      const isToday = fmtDate(d) === fmtDate(new Date());
      html += '<div class="calendar-day-col' + (isToday?' today':'') + '">';
      html += '<div class="calendar-day-header"><span>' + dayNames[i] + '</span><span class="date-num">' + d.getDate() + '</span></div>';
      filtered.forEach(function(s){
        html += '<div class="schedule-card" onclick="openEditSchedule(\\' + s.id + \\')">';
        html += '<div class="card-title">' + escHtml(s.title) + '</div>';
        html += '<div class="card-meta">';
        html += '<span class="channel-dot ' + escHtml(s.channel) + '"></span>';
        html += escHtml(s.channel) + (s.scheduled_time ? ' \\u00b7 ' + s.scheduled_time : '');
        html += ' \\u00b7 <span class="status-pill ' + escHtml(s.state) + '">' + escHtml(s.state) + '</span>';
        if(s.notion_page_id) html += ' \\u00b7 <span style="opacity:0.6;">N</span>';
        html += '</div></div>';
      });
      html += '<button class="add-schedule-btn" onclick="openNewSchedule(\\' + fmtDate(d) + \\')">+ Add</button>';
      html += '</div>';
    });
    document.getElementById('calendar-week-grid').innerHTML = html;
  };

  window.openNewSchedule = function(dateStr){
    document.getElementById('sched-id').value = '';
    document.getElementById('sched-title').value = '';
    document.getElementById('sched-channel').value = 'meta';
    document.getElementById('sched-date').value = dateStr;
    document.getElementById('sched-time').value = '';
    document.getElementById('sched-state').value = 'scheduled';
    document.getElementById('sched-notes').value = '';
    document.getElementById('sched-variant').value = '';
    document.getElementById('schedule-modal-title').textContent = 'New Schedule';
    document.getElementById('sched-delete-btn').style.display = 'none';
    document.getElementById('sched-msg').textContent = '';
    openScheduleModal();
    loadVariantOptions();
  };

  window.openEditSchedule = function(scheduleId){
    const schedules = window.__currentSchedules || [];
    const s = schedules.find(function(x){return x.id===scheduleId;});
    if(!s) return;
    document.getElementById('sched-id').value = s.id;
    document.getElementById('sched-title').value = s.title;
    document.getElementById('sched-channel').value = s.channel;
    document.getElementById('sched-date').value = s.scheduled_date;
    document.getElementById('sched-time').value = s.scheduled_time || '';
    document.getElementById('sched-state').value = s.state;
    document.getElementById('sched-notes').value = s.notes || '';
    document.getElementById('sched-variant').value = s.variant_id || '';
    document.getElementById('schedule-modal-title').textContent = 'Edit Schedule';
    document.getElementById('sched-delete-btn').style.display = '';
    document.getElementById('sched-msg').textContent = s.notion_sync_error ? 'Notion: ' + s.notion_sync_error : '';
    openScheduleModal();
    loadVariantOptions();
  };

  function openScheduleModal(){
    document.getElementById('schedule-modal').classList.add('is-open');
    document.getElementById('schedule-overlay').classList.add('open');
  }

  window.closeScheduleModal = function(){
    document.getElementById('schedule-modal').classList.remove('is-open');
    document.getElementById('schedule-overlay').classList.remove('open');
  };

  window.saveSchedule = async function(){
    const id = document.getElementById('sched-id').value;
    const title = document.getElementById('sched-title').value.trim();
    if(!title){ document.getElementById('sched-msg').textContent='Title is required.'; return; }
    const wsId = getCalendarWorkspaceId();
    const projId = getCalendarProjectId();
    const payload = {
      title: title,
      channel: document.getElementById('sched-channel').value,
      scheduled_date: document.getElementById('sched-date').value,
      scheduled_time: document.getElementById('sched-time').value || null,
      state: document.getElementById('sched-state').value,
      notes: document.getElementById('sched-notes').value || null,
      variant_id: document.getElementById('sched-variant').value || null,
    };

    try {
      let r;
      if(id){
        r = await fetch('/content-schedules/' + id, {
          method:'PUT', headers:{'Content-Type':'application/json'},
          body:JSON.stringify(payload)
        });
      } else {
        const createPayload = Object.assign({}, payload, {
          workspace_id: wsId, project_id: projId, campaign_id: null
        });
        r = await fetch('/content-schedules', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify(createPayload)
        });
      }
      if(!r.ok){ const err=await r.json(); throw new Error(err.detail||'Save failed'); }
      document.getElementById('sched-msg').textContent = 'Saved.';
      closeScheduleModal();
      loadCalendarData();
    } catch(e){
      document.getElementById('sched-msg').textContent = 'Error: ' + e.message;
    }
  };

  window.deleteSchedule = async function(){
    const id = document.getElementById('sched-id').value;
    if(!id) return;
    if(!confirm('Delete this schedule?')) return;
    try {
      const r = await fetch('/content-schedules/' + id, {method:'DELETE'});
      if(!r.ok) throw new Error('Delete failed');
      closeScheduleModal();
      loadCalendarData();
    } catch(e){
      document.getElementById('sched-msg').textContent = 'Error: ' + e.message;
    }
  };

  async function loadVariantOptions(){
    const sel = document.getElementById('sched-variant');
    if(!sel) return;
    const wsId = getCalendarWorkspaceId();
    const projId = getCalendarProjectId();
    try {
      const r = await fetch('/variants/ready-to-schedule?workspace_id=' + encodeURIComponent(wsId) + '&project_id=' + encodeURIComponent(projId));
      const data = await r.json();
      sel.innerHTML = '<option value="">-- none --</option>';
      data.forEach(function(v){
        sel.innerHTML += '<option value="' + v.variant_id + '">' +
          escHtml(v.variant_id.slice(0,8) + '... ' + (v.hook||v.message||'').slice(0,40)) +
          (v.is_winner?' [Winner]':'') + '</option>';
      });
    } catch(e){}
  }

  function escHtml(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'<').replace(/>/g,'>').replace(/"/g,'&quot;'); }

  window.addEventListener('load', function(){
    loadCalendarWorkspaces().then(function(){ loadCalendarData(); });
  });
})();
</script>
"""
