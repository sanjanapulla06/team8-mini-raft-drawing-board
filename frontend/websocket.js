
const WS = (function () {
  'use strict';

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

  // Maps stroke id
  const pendingRTT = {};

  // dom
  const statusDot    = document.getElementById('statusDot');
  const statusLabel  = document.getElementById('statusLabel');
  const strokeCountEl= document.getElementById('strokeCount');
  const clientCountEl= document.getElementById('clientCount');
  const leaderLabelEl= document.getElementById('leaderLabel');

  function uniquePush(items, seen, value) {
    if (!value || seen.has(value)) return;
    seen.add(value);
    items.push(value);
  }

  function makeGatewayCandidate(httpBase) {
    const normalized = String(httpBase || '').replace(/\/$/, '');
    if (!normalized) return null;

    let wsBase = normalized;
    if (normalized.startsWith('https://')) wsBase = 'wss://' + normalized.slice('https://'.length);
    else if (normalized.startsWith('http://')) wsBase = 'ws://' + normalized.slice('http://'.length);
    else if (normalized.startsWith('wss://') || normalized.startsWith('ws://')) {
      const baseUrl = normalized.replace(/^wss?:\/\//, normalized.startsWith('wss://') ? 'https://' : 'http://').replace(/\/ws$/, '');
      return {
        baseUrl,
        wsUrl: normalized.endsWith('/ws') ? normalized : normalized + '/ws',
        healthUrl: baseUrl + '/health'
      };
    }

    return {
      baseUrl: normalized,
      wsUrl: wsBase + '/ws',
      healthUrl: normalized + '/health'
    };
  }

  function getGatewayKey(gateway) {
    return gateway ? gateway.wsUrl : null;
  }

  function isGatewayBlocked(gateway) {
    const key = getGatewayKey(gateway);
    if (!key) return false;

    const blockedUntil = failedGateways.get(key);
    if (!blockedUntil) return false;
    if (blockedUntil <= Date.now()) {
      failedGateways.delete(key);
      return false;
    }
    return true;
  }

  function markGatewayFailed(gateway) {
    const key = getGatewayKey(gateway);
    if (!key) return;
    failedGateways.set(key, Date.now() + FAILED_GATEWAY_COOLDOWN_MS);
  }

  function rememberGateway(gateway) {
    if (!gateway || !gateway.baseUrl) return;
    localStorage.setItem('raft.gateway', gateway.baseUrl);
  }

  function getGatewayCandidates() {
    const values = [];
    const seen = new Set();
    const current = window.location;
    const params = new URLSearchParams(current.search);
    const explicit = params.get('gateway') || window.RAFT_GATEWAY_URL || localStorage.getItem('raft.gateway');

    if (explicit) {
      const explicitValue = /^(https?|wss?):\/\//.test(explicit)
        ? explicit
        : `${current.protocol === 'https:' ? 'https' : 'http'}://${explicit.replace(/^\/+/, '')}`;
      uniquePush(values, seen, explicitValue.replace(/\/$/, ''));
    }

    if (current.protocol === 'http:' || current.protocol === 'https:') {
      uniquePush(values, seen, `${current.protocol}//${current.host}`);
      DEFAULT_GATEWAY_PORTS.forEach(port => uniquePush(values, seen, `${current.protocol}//${current.hostname}:${port}`));
    }

    DEFAULT_GATEWAY_PORTS.forEach(port => {
      uniquePush(values, seen, `http://localhost:${port}`);
      uniquePush(values, seen, `http://127.0.0.1:${port}`);
    });

    return values
      .map(makeGatewayCandidate)
      .filter(candidate => candidate !== null);
  }

  function fetchWithTimeout(url, timeoutMs) {
    if (typeof AbortController !== 'function') {
      return fetch(url);
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    return fetch(url, { signal: controller.signal }).finally(() => clearTimeout(timer));
  }

  async function resolveGateway(forceRefresh) {
    if (activeGateway && !forceRefresh) return activeGateway;
    if (resolvingGateway) return null;

    resolvingGateway = true;
    try {
      const candidates = getGatewayCandidates();
      const orderedCandidates = candidates.filter(candidate => !isGatewayBlocked(candidate));
      const fallbackCandidates = orderedCandidates.length > 0 ? orderedCandidates : candidates;

      for (const candidate of fallbackCandidates) {
        try {
          const response = await fetchWithTimeout(candidate.healthUrl, 1500);
          if (!response.ok) continue;
          activeGateway = candidate;
          rememberGateway(candidate);
          return candidate;
        } catch {
          // Try the next candidate.
        }
      }

      activeGateway = fallbackCandidates[0] || null;
      return activeGateway;
    } finally {
      resolvingGateway = false;
    }
  }

  function setStatus(state, label) {
    if (statusDot) statusDot.className = 'status-dot ' + state;
    if (statusLabel) statusLabel.textContent = label;
  }

  function notify(message) {
    if (typeof window.toast === 'function') window.toast(message);
  }

  function clearReconnectTimer() {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function clearKeepaliveTimer() {
    if (keepaliveTimer !== null) {
      clearInterval(keepaliveTimer);
      keepaliveTimer = null;
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer !== null) return;
    reconnectAttempt++;
    Logger.wsRetry(reconnectAttempt, RECONNECT_MS);
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, RECONNECT_MS);
  }

  function startKeepalive() {
    clearKeepaliveTimer();
    keepaliveTimer = setInterval(() => {
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      try {
        socket.send(JSON.stringify({ type: 'keepalive' }));
      } catch (e) {
        Logger.error('keepalive send failed', e.message);
      }
    }, CLIENT_KEEPALIVE_MS);
  }

  function isStrokePayload(payload) {
    return payload && typeof payload === 'object' && Number.isFinite(payload.x) && Number.isFinite(payload.y);
  }

  // connection
  async function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    clearReconnectTimer();
    setStatus('connecting', 'Connecting…');
    const gateway = await resolveGateway(socket !== null);
    if (!gateway) {
      setStatus('disconnected', 'Disconnected');
      scheduleReconnect();
      return;
    }

    const ws = new WebSocket(gateway.wsUrl);
    socket = ws;
    let openedAt = 0;

    ws.onopen = () => {
      openedAt = Date.now();
      reconnectAttempt = 0;
      clearReconnectTimer();
      setStatus('connected', 'Connected');
      activeGateway = gateway;
      rememberGateway(gateway);
      notify('Connected to gateway');
      Logger.wsConnect(gateway.wsUrl);
      startKeepalive();

      if (openHandlers.length > 0) {
        openHandlers.forEach((handler) => {
          try {
            handler({ gateway: gateway.baseUrl, wsUrl: gateway.wsUrl });
          } catch (handlerError) {
            Logger.error('open handler failed', handlerError.message || String(handlerError));
          }
        });
      }
    };

    ws.onclose = (e) => {
      clearKeepaliveTimer();
      if (socket === ws) socket = null;
      const wasEarlyClose = openedAt > 0 && (Date.now() - openedAt) < EARLY_CLOSE_MS;
      if (wasEarlyClose || e.code === 1011 || e.code === 1006) {
        markGatewayFailed(gateway);
      }
      activeGateway = null;
      setStatus('disconnected', 'Disconnected');
      notify('Connection lost - retrying...');
      Logger.wsDisconnect(e.reason || 'socket closed');
      scheduleReconnect();
    };

    ws.onerror = () => {
      setStatus('disconnected', 'Error');
      Logger.wsError('WebSocket error event');
    };

    // stroke i/p from gateway
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);

        if (payload && typeof payload === 'object' && payload.type === 'ping') {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'pong' }));
          }
          return;
        }

        if (payload && typeof payload === 'object' && (payload.type === 'pong' || payload.type === 'keepalive')) {
          return;
        }

        if (payload && typeof payload === 'object' && payload.error) {
          Logger.error(`gateway error: ${payload.error}`);
          return;
        }

        if (!isStrokePayload(payload)) {
          Logger.error('ignored non-stroke websocket payload', event.data);
          return;
        }

        strokeCount++;
        if (strokeCountEl) strokeCountEl.textContent = `strokes: ${strokeCount}`;

        // Match back to a pending send for RTT
        const fp    = _fingerprint(payload);
        const logId = pendingRTT[fp];
        if (logId !== undefined) delete pendingRTT[fp];
        Logger.strokeReceived(payload, logId);

        if (strokeHandlers.length > 0) {
          strokeHandlers.forEach((handler) => {
            try {
              handler(payload);
            } catch (handlerError) {
              Logger.error('stroke handler failed', handlerError.message || String(handlerError));
            }
          });
        }

      } catch (e) {
        Logger.parseError(event.data);
      }
    };
  }

  // type, x, y, x0, y0, color, size 
  function sendStroke(data) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      Logger.error('Send skipped — socket not open');
      return;
    }

    const msg = {
      type:  data.erase ? 'erase' : 'draw',
      x:     data.x,
      y:     data.y,
      x0:    data.x0 ?? data.x,
      y0:    data.y0 ?? data.y,
      color: data.color,
      size:  data.size
    };

    const logId = Logger.strokeSent(data);
    pendingRTT[_fingerprint(msg)] = logId;

    try {
      socket.send(JSON.stringify(msg));
    } catch (e) {
      Logger.error('socket.send() failed', e.message);
    }
  }

  function _fingerprint(s) {
    return `${Math.round(s.x)},${Math.round(s.y)},${s.color},${s.size}`;
  }

  function onStroke(fn) {
    if (typeof fn !== 'function') return;
    strokeHandlers.push(fn);
  }

  function onOpen(fn) {
    if (typeof fn !== 'function') return;
    openHandlers.push(fn);
  }

  // health heartbeat
  let _lastLeader = null;

  async function pollHealth() {
    try {
      const gateway = activeGateway || await resolveGateway(false);
      if (!gateway) return;

      const res  = await fetchWithTimeout(gateway.healthUrl, 1500);
      const data = await res.json();

      const leader  = data.leader || null;
      const clients = data.connected_clients ?? '—';

      // Update status bar
      if (leaderLabelEl) {
        leaderLabelEl.textContent = leader
          ? `leader: ${leader.replace('http://localhost:','')}`
          : 'leader: electing…';
      }
      if (clientCountEl) clientCountEl.textContent = `peers: ${clients}`;

      // Log leader changes
      if (leader !== _lastLeader) {
        if (leader) Logger.leaderChanged(_lastLeader, leader);
        else        Logger.noLeader();
        _lastLeader = leader;
      }

    } catch {
      // Gateway not reachable — disconnected
    }
  }

  // init
  connect();
  setInterval(pollHealth, HEALTH_MS);
  pollHealth();

  return { sendStroke, onStroke, onOpen };

})();