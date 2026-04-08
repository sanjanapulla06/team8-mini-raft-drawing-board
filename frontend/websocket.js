
const WS = (function () {
  'use strict';

  const WS_URL       = 'ws://localhost:8080/ws';
  const HEALTH_URL   = 'http://localhost:8080/health';
  const RECONNECT_MS = 3000;
  const HEALTH_MS    = 2000;

  let socket           = null;
  let onStrokeHandler  = null;
  let reconnectAttempt = 0;
  let strokeCount      = 0;

  // Maps stroke id
  const pendingRTT = {};

  // dom
  const statusDot    = document.getElementById('statusDot');
  const statusLabel  = document.getElementById('statusLabel');
  const strokeCountEl= document.getElementById('strokeCount');
  const clientCountEl= document.getElementById('clientCount');
  const leaderLabelEl= document.getElementById('leaderLabel');

  function setStatus(state, label) {
    statusDot.className     = 'status-dot ' + state;
    statusLabel.textContent = label;
  }

  // connection
  function connect() {
    setStatus('connecting', 'Connecting…');
    socket = new WebSocket(WS_URL);

    socket.onopen = () => {
      reconnectAttempt = 0;
      setStatus('connected', 'Connected');
      window.toast('🌸 Connected to Bloom');
      Logger.wsConnect(WS_URL);
    };

    socket.onclose = (e) => {
      setStatus('disconnected', 'Disconnected');
      window.toast('Connection lost — retrying…');
      Logger.wsDisconnect(e.reason || 'socket closed');
      reconnectAttempt++;
      Logger.wsRetry(reconnectAttempt, RECONNECT_MS);
      setTimeout(connect, RECONNECT_MS);
    };

    socket.onerror = () => {
      setStatus('disconnected', 'Error');
      Logger.wsError('WebSocket error event');
    };

    // stroke i/p from gateway
    socket.onmessage = (event) => {
      try {
        const stroke = JSON.parse(event.data);

        strokeCount++;
        if (strokeCountEl) strokeCountEl.textContent = `strokes: ${strokeCount}`;

        // Match back to a pending send for RTT
        const fp    = _fingerprint(stroke);
        const logId = pendingRTT[fp];
        if (logId !== undefined) delete pendingRTT[fp];
        Logger.strokeReceived(stroke, logId);

        if (typeof onStrokeHandler === 'function') onStrokeHandler(stroke);

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

  function onStroke(fn) { onStrokeHandler = fn; }

  // health heartbeat
  let _lastLeader = null;

  async function pollHealth() {
    try {
      const res  = await fetch(HEALTH_URL, { signal: AbortSignal.timeout(1500) });
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

  return { sendStroke, onStroke };

})();