const Logger = (function () 
{  'use strict';
  // Internal store 
  const entries = [];          
  const pending = {};      
  let   seq     = 0;           
  let   activeFilter = 'all';
  //latenvy
  const latSamples = [];
  let   totalRTT   = 0;

  function pushLatency(ms) 
  {
    latSamples.push(ms);
    totalRTT += ms;
    if (latSamples.length > 200) totalRTT -= latSamples.shift();
    const avg = Math.round(totalRTT / latSamples.length);
    const el  = document.getElementById('logAvgLatency');
    if (el) el.textContent = `avg RTT: ${avg} ms`;
  }

  // timestamp
  function ts() 
  {
    const n = new Date();
    return [n.getHours(), n.getMinutes(), n.getSeconds()]
      .map(v => String(v).padStart(2,'0')).join(':')
      + '.' + String(n.getMilliseconds()).padStart(3,'0');
  }

  // level: info-warning-error-latency
  // category: ws-stroke-latency-error-leader elected-info
  function add(level, category, message, detail) 
  {
    const entry = { id: entries.length, ts: ts(), epoch: Date.now(), level, category, message, detail: detail || null };
    entries.push(entry);
    _renderEntry(entry);
    const countEl = document.getElementById('logEntryCount');
    if (countEl) countEl.textContent = `${entries.length} events`;
    return entry;
  }

  // logs entry
  function _renderEntry(entry) 
  {
    const body = document.getElementById('logBody');
    if (!body) return;
    // remove empty state
    const empty = body.querySelector('.log-empty');
    if (empty) empty.remove();
    // filter
    if (activeFilter !== 'all' && entry.category !== activeFilter) return;

    const row = document.createElement('div');
    row.className = `log-row log-${entry.level}`;
    row.dataset.category = entry.category;
    row.dataset.id = entry.id;
    row.innerHTML = `
      <span class="log-ts">${entry.ts}</span>
      <span class="log-cat log-cat-${entry.category}">${entry.category.toUpperCase()}</span>
      <span class="log-msg">${_escape(entry.message)}</span>
      ${entry.detail ? `<span class="log-detail">${_escape(entry.detail)}</span>` : '<span></span>'}
    `;

    body.appendChild(row);
    while (body.children.length > 300) body.removeChild(body.firstChild);
    // auto scroll 
    body.scrollTop = body.scrollHeight;
  }

  //  re-rendering all the entries for a filter 
  function _applyFilter(filter) 
  {
    activeFilter = filter;
    const body = document.getElementById('logBody');
    if (!body) return;
    body.innerHTML = '';
    const filtered = filter === 'all' ? entries : entries.filter(e => e.category === filter);
    if (filtered.length === 0) 
    {
      body.innerHTML = `<div class="log-empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
        </svg>
        <span>No ${filter === 'all' ? '' : filter + ' '}events yet</span>
      </div>`;
      return;
    }
    filtered.forEach(_renderEntry);
  }

  function _escape(s) 
  {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }
  // status dot sync
  function _syncLogStatus(state, label) 
  {
    const dot = document.getElementById('logStatusDot');
    const lbl = document.getElementById('logStatusLabel');
    if (dot) dot.className = 'stat-dot ' + state;
    if (lbl) lbl.textContent = label;
  }

  //--------------------------------------------------------------------------------------

  // web sock 
  function wsConnect(url) 
  {
    add('info','ws',`Connected to gateway`,url);
    _syncLogStatus('connected','Connected');
  }
  function wsDisconnect(reason) 
  {
    add('warn','ws',`Disconnected`,reason || '—');
    _syncLogStatus('disconnected','Disconnected');
  }
  function wsRetry(attempt, ms) 
  {
    add('warn','ws',`Reconnect attempt #${attempt}`,`retry in ${ms}ms`);
    _syncLogStatus('connecting','Reconnecting…');
  }
  function wsError(msg) 
  {
    add('error','error',`WebSocket error`,msg);
  }

  // stroke lifecylce
  function strokeSent(data) 
  {
    const id = ++seq;
    pending[id] = Date.now();
    add('info','stroke',
      `#${id} sent [${data.erase ? 'erase':'draw'}]`,
      `x:${Math.round(data.x)} y:${Math.round(data.y)} color:${data.color} size:${data.size}`
    );
    return id;
  }

  function strokeReceived(data, strokeId) 
  {
    let rttNote = '';
    if (strokeId != null && pending[strokeId] !== undefined) 
    {
      const rtt = Date.now() - pending[strokeId];
      delete pending[strokeId];
      pushLatency(rtt);
      rttNote = `RTT ${rtt}ms`;
    }
    add('latency','latency', strokeId ? `#${strokeId} committed` : 'Stroke received', rttNote || null);
  }

  //leader change
  function leaderChanged(from, to) 
  {
    add('info','leader', `Leader changed`, `${from || 'none'} → ${to || 'none'}`);
    const el = document.getElementById('logLeader');
    if (el) el.textContent = `leader: ${to ? to.replace('http://localhost:','') : '—'}`;
  }
  function noLeader() 
  {
    add('warn','leader','No leader found — election in progress');
    const el = document.getElementById('logLeader');
    if (el) el.textContent = 'leader: electing…';
  }

  function error(msg, detail) 
  { 
    add('error','error', msg, detail); 
  }
  function parseError(raw)    
  { 
    add('error','error','Parse error on incoming message', String(raw).slice(0,80)); 
  }
  function info(msg, detail)  
  { 
    add('info','info', msg, detail); 
  }

  //download
  function download() 
  {
    const avg = latSamples.length
      ? Math.round(totalRTT / latSamples.length) + ' ms'
      : 'N/A';

    const header = [
      '***',
      '  Bloom — Distributed Drawing Board  |  Log File',
      `  Start   : ${new Date(entries[0]?.epoch || Date.now()).toLocaleString()}`,
      `  End     : ${new Date().toLocaleString()}`,
      `  Events  : ${entries.length}`,
      `  Avg RTT : ${avg}`,
      '***',
      ''
    ].join('\n');

    const lines = entries.map(e => 
    {
      const detail = e.detail ? `  |  ${e.detail}` : '';
      return `[${e.ts}] [${e.level.toUpperCase().padEnd(7)}] [${e.category.toUpperCase().padEnd(7)}] ${e.message}${detail}`;
    }
  ).join('\n');
    const blob = new Blob([header + lines], { type: 'text/plain' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `bloom-log-${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    window.toast('Log downloaded');
  }

  //delete
  function clear() 
  {
    entries.length = 0;
    latSamples.length = 0;
    totalRTT = 0;
    seq = 0;
    const body = document.getElementById('logBody');
    if (body) body.innerHTML = '';
    const countEl = document.getElementById('logEntryCount');
    if (countEl) countEl.textContent = '0 events';
    const avgEl = document.getElementById('logAvgLatency');
    if (avgEl) avgEl.textContent = 'avg RTT: —';
    window.toast('Logs cleared');
  }

  // brush and palette
  function openLogs() 
  {
    document.getElementById('logsView').classList.add('open');
    _applyFilter(activeFilter);
  }
  function closeLogs() 
  {
    document.getElementById('logsView').classList.remove('open');
  }

  // buttons
  document.addEventListener('DOMContentLoaded', () => 
  {
    document.getElementById('btnOpenLogs')?.addEventListener('click', openLogs);
    document.getElementById('btnCloseLogs')?.addEventListener('click', closeLogs);
    document.getElementById('btnClearLogs')?.addEventListener('click', clear);
    document.getElementById('btnDownloadLogs')?.addEventListener('click', download);
  
    document.querySelectorAll('.filter-btn').forEach(btn => 
    {
      btn.addEventListener('click', () => 
      {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        _applyFilter(btn.dataset.filter);
      }
    );
    }
  );

    // initial state - empty 
    _applyFilter('all');
  }
);

  return {
    wsConnect, wsDisconnect, wsRetry, wsError,
    strokeSent, strokeReceived,
    leaderChanged, noLeader,
    error, parseError, info,
    download, clear, openLogs, closeLogs
  };

})();