const WS = (function () 
{  'use strict';
  const RECONNECT_MS = 3000;
  const HEALTH_MS    = 2000;
  const CLIENT_KEEPALIVE_MS = 10000;
  const DEFAULT_GATEWAY_PORTS = ['8090', '8000', '8080'];
  const FAILED_GATEWAY_COOLDOWN_MS = 30000;
  const EARLY_CLOSE_MS = 30000;
  let socket           = null;
  const strokeHandlers = [];
  const openHandlers   = [];
  let reconnectAttempt = 0;
  let strokeCount      = 0;
  let reconnectTimer   = null;
  let keepaliveTimer   = null;
  let activeGateway    = null;
  let resolvingGateway = false;
  const failedGateways = new Map();
  const pendingRTT     = {};

  const statusDot     = document.getElementById('statusDot');
  const statusLabel   = document.getElementById('statusLabel');
  const strokeCountEl = document.getElementById('strokeCount');
  const clientCountEl = document.getElementById('clientCount');
  const leaderLabelEl = document.getElementById('leaderLabel');

  function uniquePush(items, seen, value) 
  {
    if (!value || seen.has(value)) return;
    seen.add(value);
    items.push(value);
  }

  function makeGatewayCandidate(httpBase) 
  {
    const normalized = String(httpBase || '').replace(/\/$/, '');
    if (!normalized) return null;
    let wsBase = normalized;
    if (normalized.startsWith('https://'))      
      wsBase = 'wss://' + normalized.slice('https://'.length);
    else if (normalized.startsWith('http://'))  
      wsBase = 'ws://'  + normalized.slice('http://'.length);
    else if (normalized.startsWith('wss://') || normalized.startsWith('ws://')) 
    {
      const baseUrl = normalized
        .replace(/^wss?:\/\//, normalized.startsWith('wss://') ? 'https://' : 'http://')
        .replace(/\/ws$/, '');
      return { baseUrl, wsUrl: normalized.endsWith('/ws') ? normalized : normalized + '/ws', healthUrl: baseUrl + '/health' };
    }
    return { baseUrl: normalized, wsUrl: wsBase + '/ws', healthUrl: normalized + '/health' };
  }

  function getGatewayKey(g)    
  { 
    return g ? g.wsUrl : null; 
  }

  function isGatewayBlocked(g) 
  {
    const key = getGatewayKey(g);
    if (!key) return false;
      const until = failedGateways.get(key);
    if (!until) 
      return false;
    if (until <= Date.now()) 
      { failedGateways.delete(key); return false; }
    return true;
  }

  function markGatewayFailed(g) 
  {
    const key = getGatewayKey(g);
    if (key) 
      failedGateways.set(key, Date.now() + FAILED_GATEWAY_COOLDOWN_MS);
  }

  function rememberGateway(g) 
  {
    if (g && g.baseUrl) 
      localStorage.setItem('raft.gateway', g.baseUrl);
  }

  function getGatewayCandidates() 
  {
    const values = [], seen = new Set();
    const current = window.location;
    const params  = new URLSearchParams(current.search);
    const explicit = params.get('gateway') || window.RAFT_GATEWAY_URL || localStorage.getItem('raft.gateway');
    if (explicit) 
    {
      const v = /^(https?|wss?):\/\//.test(explicit)
        ? explicit
        : `${current.protocol === 'https:' ? 'https' : 'http'}://${explicit.replace(/^\/+/, '')}`;
      uniquePush(values, seen, v.replace(/\/$/, ''));
    }
    if (current.protocol === 'http:' || current.protocol === 'https:') 
    {
      uniquePush(values, seen, `${current.protocol}//${current.host}`);
      DEFAULT_GATEWAY_PORTS.forEach(p => uniquePush(values, seen, `${current.protocol}//${current.hostname}:${p}`));
    }
    DEFAULT_GATEWAY_PORTS.forEach(p => 
    {
      uniquePush(values, seen, `http://localhost:${p}`);
      uniquePush(values, seen, `http://127.0.0.1:${p}`);
    }
  );
    return values.map(makeGatewayCandidate).filter(Boolean);
  }

  function fetchWithTimeout(url, ms) 
  {
    if (typeof AbortController !== 'function') return fetch(url);
    const ctrl  = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), ms);
    return fetch(url, { signal: ctrl.signal }).finally(() => clearTimeout(timer));
  }

  async function resolveGateway(forceRefresh) 
  {
    if (activeGateway && !forceRefresh) return activeGateway;
    if (resolvingGateway) return null;
    resolvingGateway = true;
    try 
    {
      const candidates = getGatewayCandidates();
      const ordered    = candidates.filter(c => !isGatewayBlocked(c));
      const list       = ordered.length > 0 ? ordered : candidates;
      for (const c of list) {
        try {
          const r = await fetchWithTimeout(c.healthUrl, 1500);
          if (!r.ok) continue;
          activeGateway = c;
          rememberGateway(c);
          return c;
        } 
        catch { /* next */ }
      }
      activeGateway = list[0] || null;
      return activeGateway;
    } 
    finally 
    {
      resolvingGateway = false;
    }
  }

  function setStatus(state, label) 
  {
    if (statusDot)   statusDot.className     = 'status-dot ' + state;
    if (statusLabel) statusLabel.textContent = label;
  }

  function notify(msg) 
  { 
    if (typeof window.toast === 'function') window.toast(msg); 
  }

  function clearReconnectTimer() 
  { 
    if (reconnectTimer !== null) { clearTimeout(reconnectTimer);  reconnectTimer  = null; } 
  }

  function clearKeepaliveTimer() 
  { 
    if (keepaliveTimer !== null) { clearInterval(keepaliveTimer); keepaliveTimer  = null; } 
  }

  function scheduleReconnect() 
  {
    if (reconnectTimer !== null) return;
    reconnectAttempt++;
    Logger.wsRetry(reconnectAttempt, RECONNECT_MS);
    reconnectTimer = setTimeout(() => { reconnectTimer = null; connect(); }, RECONNECT_MS);
  }

  function startKeepalive() 
  {
    clearKeepaliveTimer();
    keepaliveTimer = setInterval(() => 
      {
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      try { socket.send(JSON.stringify({ type: 'keepalive' })); }
      catch (e) { Logger.error('keepalive send failed', e.message); }
    }, 
    CLIENT_KEEPALIVE_MS);
  }

  function isStrokePayload(p) 
  {
    return p && typeof p === 'object' && Number.isFinite(p.x) && Number.isFinite(p.y);
  }

  async function connect() 
  {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
    clearReconnectTimer();
    setStatus('connecting', 'Connecting…');
    const gateway = await resolveGateway(socket !== null);
    if (!gateway) 
      { setStatus('disconnected', 'Disconnected'); scheduleReconnect(); return; }
    const ws = new WebSocket(gateway.wsUrl);
    socket = ws;
    let openedAt = 0;

    ws.onopen = () => 
    {
      openedAt = Date.now();
      reconnectAttempt = 0;
      clearReconnectTimer();
      setStatus('connected', 'Connected');
      activeGateway = gateway;
      rememberGateway(gateway);
      notify('Connected to gateway');
      Logger.wsConnect(gateway.wsUrl);
      startKeepalive();
      openHandlers.forEach(h => 
      { 
        try { h({ gateway: gateway.baseUrl, wsUrl: gateway.wsUrl }); } 
        catch(e) { Logger.error('open handler failed', String(e)); } 
      }
    );
    };

    ws.onclose = (e) => 
    {
      clearKeepaliveTimer();
      if (socket === ws) socket = null;
      const earlyClose = openedAt > 0 && (Date.now() - openedAt) < EARLY_CLOSE_MS;
      if (earlyClose || e.code === 1011 || e.code === 1006) markGatewayFailed(gateway);
      activeGateway = null;
      setStatus('disconnected', 'Disconnected');
      notify('Connection lost - retrying...');
      Logger.wsDisconnect(e.reason || 'socket closed');
      scheduleReconnect();
    };

    ws.onerror = () => 
    { setStatus('disconnected', 'Error'); Logger.wsError('WebSocket error event'); };

    ws.onmessage = (event) => 
    {
      try 
      {
        const payload = JSON.parse(event.data);
        if (payload && typeof payload === 'object' && payload.type === 'ping') 
        {
          if (ws.readyState === WebSocket.OPEN) 
            ws.send(JSON.stringify({ type: 'pong' }));
          return;
        }
        if (payload && typeof payload === 'object' && (payload.type === 'pong' || payload.type === 'keepalive')) 
          return;
        if (payload && typeof payload === 'object' && payload.error) 
          { Logger.error(`gateway error: ${payload.error}`); 
            return; }
        if (!isStrokePayload(payload)) 
          { Logger.error('ignored non-stroke payload', event.data); 
            return; }
        strokeCount++;
        if (strokeCountEl) 
          strokeCountEl.textContent = `strokes: ${strokeCount}`;

        const fp = _fingerprint(payload);
        const logId = pendingRTT[fp];
        if (logId !== undefined) 
          delete pendingRTT[fp];
        Logger.strokeReceived(payload, logId);
        strokeHandlers.forEach(h => { try { h(payload); } catch(e) { Logger.error('stroke handler failed', String(e)); } });
      } 
      catch (e) 
      { Logger.parseError(event.data); }
    };
  }

  let _clientId = '';
  let _peerName = '';
  let _peerColor = '';

  function setClientId(id, name, color) 
  {
    _clientId = id || '';
    _peerName = name || '';
    _peerColor = color || '';
  }

  function sendStroke(data) 
  {
    if (!socket || socket.readyState !== WebSocket.OPEN) 
      { Logger.error('Send skipped — socket not open'); return; }
    const msg = 
    {
      type: data.erase ? 'erase' : (data.shape ? 'shape' : 'draw'),
      clientId: _clientId,
      peerName: _peerName,
      peerColor: _peerColor,
      x: data.x,
      y: data.y,
      x0: data.x0 ?? data.x,
      y0: data.y0 ?? data.y,
      color: data.color,
      size: data.size,
      brush: data.brush || 'pen',
      ...(data.shape ? { shape: data.shape } : {})
    };

    const logId = Logger.strokeSent(data);
    pendingRTT[_fingerprint(msg)] = logId;
    try 
      { socket.send(JSON.stringify({
        stroke: msg
      }));
    }
    catch (e) { Logger.error('socket.send() failed', e.message); }
  }

  function _fingerprint(s) 
  { 
    return `${Math.round(s.x)},${Math.round(s.y)},${s.color},${s.size}`; 
  }

  function onStroke(fn) 
  { 
    if (typeof fn === 'function') strokeHandlers.push(fn); 
  }

  function onOpen(fn)   
  { 
    if (typeof fn === 'function') openHandlers.push(fn); 

  }

  let _lastLeader = null;
  async function pollHealth() 
  {
    try 
    {
      const gateway = activeGateway || await resolveGateway(false);
      if (!gateway) return;
      const res  = await fetchWithTimeout(gateway.healthUrl, 1500);
      const data = await res.json();
      const leader  = data.leader || null;
      const clients = data.connected_clients ?? '—';
      if (leaderLabelEl) leaderLabelEl.textContent = leader ? `leader: ${leader.replace('http://localhost:','')}` : 'leader: electing…';
      if (clientCountEl) clientCountEl.textContent = `peers: ${clients}`;
      if (leader !== _lastLeader) {
        if (leader) Logger.leaderChanged(_lastLeader, leader);
        else        Logger.noLeader();
        _lastLeader = leader;
      }
    } 
    catch { /* not reachable */ }
  }

  connect();
  setInterval(pollHealth, HEALTH_MS);
  pollHealth();

  return { sendStroke, onStroke, onOpen, setClientId };

})();
