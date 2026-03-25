// // ─── app.js ──────────────────────────────────────────────────────────────────
// // Mini RAFT Drawing Board — Frontend Client
// // Handles: canvas drawing, stroke events, WebSocket comms with gateway
// // ─────────────────────────────────────────────────────────────────────────────

// (function () {

//   // ── Canvas setup ────────────────────────────────────────────────────────────
//   const canvas  = document.getElementById('canvas');
//   const ctx     = canvas.getContext('2d');

//   // Size canvas to fill the available area nicely
//   function resizeCanvas() {
//     const area   = document.querySelector('.canvas-area');
//     const pad    = 40;
//     const maxW   = area.clientWidth  - pad;
//     const maxH   = area.clientHeight - pad;

//     // Preserve drawn content by snapshotting before resize
//     const snapshot = ctx.getImageData(0, 0, canvas.width, canvas.height);

//     canvas.width  = Math.floor(Math.min(maxW, 1200));
//     canvas.height = Math.floor(Math.min(maxH, 800));

//     // Restore content after resize
//     ctx.putImageData(snapshot, 0, 0);
//     applyCtxStyle();
//   }

//   function applyCtxStyle() {
//     ctx.lineCap   = 'round';
//     ctx.lineJoin  = 'round';
//     ctx.lineWidth = brushSize;
//     ctx.strokeStyle = currentColor;
//   }

//   // ── State ────────────────────────────────────────────────────────────────────
//   let drawing      = false;
//   let currentColor = '#f9a8d4';
//   let brushSize    = 3;
//   let isErasing    = false;
//   let lastX        = null;
//   let lastY        = null;

//   // ── WebSocket ────────────────────────────────────────────────────────────────
//   const WS_URL = 'ws://localhost:8080/ws';
//   let   ws     = null;

//   const statusDot   = document.getElementById('statusDot');
//   const statusLabel = document.getElementById('statusLabel');

//   function setStatus(state, label) {
//     statusDot.className = 'status-dot ' + state;
//     statusLabel.textContent = label;
//   }

//   function connectWS() {
//     setStatus('connecting', 'Connecting…');

//     ws = new WebSocket(WS_URL);

//     ws.onopen = () => {
//       setStatus('connected', 'Connected');
//       console.log('[WS] Connected to gateway');
//     };

//     ws.onclose = () => {
//       setStatus('disconnected', 'Disconnected');
//       console.warn('[WS] Disconnected — retrying in 3s…');
//       setTimeout(connectWS, 3000);   // auto-reconnect
//     };

//     ws.onerror = (err) => {
//       console.error('[WS] Error:', err);
//       setStatus('disconnected', 'Error');
//     };

//     // ── Receive strokes from other clients via gateway ────────────────────────
//     ws.onmessage = (event) => {
//       try {
//         const msg = JSON.parse(event.data);
//         if (msg.type === 'stroke') {
//           renderRemoteStroke(msg);
//         }
//       } catch (e) {
//         console.warn('[WS] Could not parse message:', event.data);
//       }
//     };
//   }

//   // ── Send a stroke segment to the gateway ────────────────────────────────────
//   function sendStroke(strokeData) {
//     if (!ws || ws.readyState !== WebSocket.OPEN) return;
//     const msg = {
//       type:   'stroke',
//       x:      strokeData.x,
//       y:      strokeData.y,
//       x0:     strokeData.x0,
//       y0:     strokeData.y0,
//       color:  strokeData.color,
//       size:   strokeData.size,
//       erase:  strokeData.erase
//     };
//     ws.send(JSON.stringify(msg));
//   }

//   // ── Draw a stroke segment on the canvas ─────────────────────────────────────
//   function drawSegment(x0, y0, x1, y1, color, size, erase) {
//     ctx.save();

//     if (erase) {
//       ctx.globalCompositeOperation = 'destination-out';
//       ctx.strokeStyle = 'rgba(0,0,0,1)';
//     } else {
//       ctx.globalCompositeOperation = 'source-over';
//       ctx.strokeStyle = color;
//     }

//     ctx.lineWidth  = size;
//     ctx.lineCap    = 'round';
//     ctx.lineJoin   = 'round';

//     ctx.beginPath();
//     ctx.moveTo(x0, y0);
//     ctx.lineTo(x1, y1);
//     ctx.stroke();

//     ctx.restore();
//   }

//   // ── Render a stroke received from another client ─────────────────────────────
//   function renderRemoteStroke(msg) {
//     drawSegment(msg.x0, msg.y0, msg.x, msg.y, msg.color, msg.size, msg.erase);
//   }

//   // ── Get position relative to canvas ─────────────────────────────────────────
//   function getPos(e) {
//     const rect = canvas.getBoundingClientRect();
//     const scaleX = canvas.width  / rect.width;
//     const scaleY = canvas.height / rect.height;

//     if (e.touches) {
//       const t = e.touches[0];
//       return {
//         x: (t.clientX - rect.left) * scaleX,
//         y: (t.clientY - rect.top)  * scaleY
//       };
//     }
//     return {
//       x: (e.clientX - rect.left) * scaleX,
//       y: (e.clientY - rect.top)  * scaleY
//     };
//   }

//   // ── Coordinate display ───────────────────────────────────────────────────────
//   const coordDisplay = document.getElementById('coordDisplay');

//   function updateCoords(x, y) {
//     coordDisplay.textContent = `x: ${Math.round(x)}   y: ${Math.round(y)}`;
//   }

//   // ── Pointer events ───────────────────────────────────────────────────────────
//   function onPointerDown(e) {
//     e.preventDefault();
//     drawing = true;
//     const { x, y } = getPos(e);
//     lastX = x;
//     lastY = y;

//     // Draw a dot for click/tap with no movement
//     drawSegment(x, y, x, y, currentColor, brushSize, isErasing);
//     sendStroke({ x, y, x0: x, y0: y, color: currentColor, size: brushSize, erase: isErasing });
//   }

//   function onPointerMove(e) {
//     e.preventDefault();
//     const { x, y } = getPos(e);
//     updateCoords(x, y);

//     if (!drawing) return;

//     drawSegment(lastX, lastY, x, y, currentColor, brushSize, isErasing);
//     sendStroke({ x, y, x0: lastX, y0: lastY, color: currentColor, size: brushSize, erase: isErasing });

//     lastX = x;
//     lastY = y;
//   }

//   function onPointerUp(e) {
//     drawing = false;
//     lastX   = null;
//     lastY   = null;
//   }

//   // Mouse
//   canvas.addEventListener('mousedown',  onPointerDown);
//   canvas.addEventListener('mousemove',  onPointerMove);
//   canvas.addEventListener('mouseup',    onPointerUp);
//   canvas.addEventListener('mouseleave', onPointerUp);

//   // Touch (mobile / tablet)
//   canvas.addEventListener('touchstart',  onPointerDown, { passive: false });
//   canvas.addEventListener('touchmove',   onPointerMove, { passive: false });
//   canvas.addEventListener('touchend',    onPointerUp);
//   canvas.addEventListener('touchcancel', onPointerUp);

//   // ── Toolbar: colour swatches ─────────────────────────────────────────────────
//   document.getElementById('colorSwatches').addEventListener('click', (e) => {
//     const btn = e.target.closest('.swatch');
//     if (!btn) return;

//     document.querySelectorAll('.swatch').forEach(s => s.classList.remove('active'));
//     btn.classList.add('active');

//     currentColor = btn.dataset.color;
//     document.getElementById('colorPicker').value = currentColor;

//     // Switch back to draw if we were erasing
//     if (isErasing) activateDraw();
//   });

//   // ── Toolbar: custom colour picker ────────────────────────────────────────────
//   document.getElementById('colorPicker').addEventListener('input', (e) => {
//     currentColor = e.target.value;
//     document.querySelectorAll('.swatch').forEach(s => s.classList.remove('active'));
//     if (isErasing) activateDraw();
//   });

//   // ── Toolbar: brush size ──────────────────────────────────────────────────────
//   document.getElementById('sizeOptions').addEventListener('click', (e) => {
//     const btn = e.target.closest('.size-btn');
//     if (!btn) return;
//     document.querySelectorAll('.size-btn').forEach(b => b.classList.remove('active'));
//     btn.classList.add('active');
//     brushSize = parseInt(btn.dataset.size, 10);
//   });

//   // ── Toolbar: draw / erase ────────────────────────────────────────────────────
//   function activateDraw() {
//     isErasing = false;
//     document.getElementById('btnDraw').classList.add('active');
//     document.getElementById('btnErase').classList.remove('active');
//     canvas.style.cursor = 'crosshair';
//   }

//   function activateErase() {
//     isErasing = true;
//     document.getElementById('btnErase').classList.add('active');
//     document.getElementById('btnDraw').classList.remove('active');
//     canvas.style.cursor = 'cell';
//   }

//   document.getElementById('btnDraw').addEventListener('click',  activateDraw);
//   document.getElementById('btnErase').addEventListener('click', activateErase);

//   // ── Toolbar: clear canvas ────────────────────────────────────────────────────
//   document.getElementById('btnClear').addEventListener('click', () => {
//     ctx.clearRect(0, 0, canvas.width, canvas.height);

//     // Notify other clients
//     if (ws && ws.readyState === WebSocket.OPEN) {
//       ws.send(JSON.stringify({ type: 'clear' }));
//     }
//   });

//   // Also handle a 'clear' event from other clients
//   const _origOnMessage = null;
//   // We patch the clear-handling into ws.onmessage above via the type check

//   // ── Window resize ────────────────────────────────────────────────────────────
//   window.addEventListener('resize', resizeCanvas);

//   // ── Init ─────────────────────────────────────────────────────────────────────
//   resizeCanvas();
//   connectWS();

// })();



// ─── app.js ──────────────────────────────────────────────────────────────────
// Mini RAFT Drawing Board — Frontend Client
// Handles: canvas drawing, stroke events, WebSocket comms with gateway
// ─────────────────────────────────────────────────────────────────────────────

(function () {

  // ── Canvas setup ────────────────────────────────────────────────────────────
  const canvas  = document.getElementById('canvas');
  const ctx     = canvas.getContext('2d');

  // Size canvas to fill the available area nicely
  function resizeCanvas() {
    const area   = document.querySelector('.canvas-area');
    const pad    = 40;
    const maxW   = area.clientWidth  - pad;
    const maxH   = area.clientHeight - pad;

    // Preserve drawn content by snapshotting before resize
    const snapshot = ctx.getImageData(0, 0, canvas.width, canvas.height);

    canvas.width  = Math.floor(Math.min(maxW, 1200));
    canvas.height = Math.floor(Math.min(maxH, 800));

    // Restore content after resize
    ctx.putImageData(snapshot, 0, 0);
    applyCtxStyle();
  }

  function applyCtxStyle() {
    ctx.lineCap   = 'round';
    ctx.lineJoin  = 'round';
    ctx.lineWidth = brushSize;
    ctx.strokeStyle = currentColor;
  }

  // ── State ────────────────────────────────────────────────────────────────────
  let drawing      = false;
  let currentColor = '#f9a8d4';
  let brushSize    = 3;
  let isErasing    = false;
  let lastX        = null;
  let lastY        = null;

  // ── WebSocket ────────────────────────────────────────────────────────────────
  const WS_URL = 'ws://localhost:8080/ws';
  let   ws     = null;

  const statusDot   = document.getElementById('statusDot');
  const statusLabel = document.getElementById('statusLabel');

  function setStatus(state, label) {
    statusDot.className = 'status-dot ' + state;
    statusLabel.textContent = label;
  }

  function connectWS() {
    setStatus('connecting', 'Connecting…');

    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      setStatus('connected', 'Connected');
      console.log('[WS] Connected to gateway');
    };

    ws.onclose = () => {
      setStatus('disconnected', 'Disconnected');
      console.warn('[WS] Disconnected — retrying in 3s…');
      setTimeout(connectWS, 3000);   // auto-reconnect
    };

    ws.onerror = (err) => {
      console.error('[WS] Error:', err);
      setStatus('disconnected', 'Error');
    };

    // ── Receive strokes from other clients via gateway ────────────────────────
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        // Handle both a single stroke object and a batched array of strokes
        const strokes = Array.isArray(data) ? data : [data];
        for (const msg of strokes) {
          if (msg.type === 'stroke') renderRemoteStroke(msg);
          else if (msg.type === 'clear') ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
      } catch (e) {
        console.warn('[WS] Could not parse message:', event.data);
      }
    };
  }

  // ── Throttled send — batches strokes per animation frame (~16ms) ────────────
  let pendingStrokes  = [];
  let flushScheduled  = false;

  function flushStrokes() {
    flushScheduled = false;
    if (!ws || ws.readyState !== WebSocket.OPEN) { pendingStrokes = []; return; }
    if (pendingStrokes.length === 0) return;

    // Send all pending strokes in one JSON array — fewer WebSocket frames
    ws.send(JSON.stringify(pendingStrokes));
    pendingStrokes = [];
  }

  function sendStroke(strokeData) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    pendingStrokes.push({
      type:  'stroke',
      x:     strokeData.x,
      y:     strokeData.y,
      x0:    strokeData.x0,
      y0:    strokeData.y0,
      color: strokeData.color,
      size:  strokeData.size,
      erase: strokeData.erase
    });
    if (!flushScheduled) {
      flushScheduled = true;
      requestAnimationFrame(flushStrokes);
    }
  }

  // ── Draw a stroke segment on the canvas ─────────────────────────────────────
  function drawSegment(x0, y0, x1, y1, color, size, erase) {
    ctx.save();

    if (erase) {
      ctx.globalCompositeOperation = 'destination-out';
      ctx.strokeStyle = 'rgba(0,0,0,1)';
    } else {
      ctx.globalCompositeOperation = 'source-over';
      ctx.strokeStyle = color;
    }

    ctx.lineWidth  = size;
    ctx.lineCap    = 'round';
    ctx.lineJoin   = 'round';

    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();

    ctx.restore();
  }

  // ── Render a stroke received from another client ─────────────────────────────
  function renderRemoteStroke(msg) {
    drawSegment(msg.x0, msg.y0, msg.x, msg.y, msg.color, msg.size, msg.erase);
  }

  // ── Get position relative to canvas ─────────────────────────────────────────
  function getPos(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width  / rect.width;
    const scaleY = canvas.height / rect.height;

    if (e.touches) {
      const t = e.touches[0];
      return {
        x: (t.clientX - rect.left) * scaleX,
        y: (t.clientY - rect.top)  * scaleY
      };
    }
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top)  * scaleY
    };
  }

  // ── Coordinate display ───────────────────────────────────────────────────────
  const coordDisplay = document.getElementById('coordDisplay');

  function updateCoords(x, y) {
    coordDisplay.textContent = `x: ${Math.round(x)}   y: ${Math.round(y)}`;
  }

  // ── Pointer events ───────────────────────────────────────────────────────────
  function onPointerDown(e) {
    e.preventDefault();
    drawing = true;
    const { x, y } = getPos(e);
    lastX = x;
    lastY = y;

    // Draw a dot for click/tap with no movement
    drawSegment(x, y, x, y, currentColor, brushSize, isErasing);
    sendStroke({ x, y, x0: x, y0: y, color: currentColor, size: brushSize, erase: isErasing });
  }

  function onPointerMove(e) {
    e.preventDefault();
    const { x, y } = getPos(e);
    updateCoords(x, y);

    if (!drawing) return;

    drawSegment(lastX, lastY, x, y, currentColor, brushSize, isErasing);
    sendStroke({ x, y, x0: lastX, y0: lastY, color: currentColor, size: brushSize, erase: isErasing });

    lastX = x;
    lastY = y;
  }

  function onPointerUp(e) {
    drawing = false;
    lastX   = null;
    lastY   = null;
  }

  // Mouse
  canvas.addEventListener('mousedown',  onPointerDown);
  canvas.addEventListener('mousemove',  onPointerMove);
  canvas.addEventListener('mouseup',    onPointerUp);
  canvas.addEventListener('mouseleave', onPointerUp);

  // Touch (mobile / tablet)
  canvas.addEventListener('touchstart',  onPointerDown, { passive: false });
  canvas.addEventListener('touchmove',   onPointerMove, { passive: false });
  canvas.addEventListener('touchend',    onPointerUp);
  canvas.addEventListener('touchcancel', onPointerUp);

  // ── Toolbar: colour swatches ─────────────────────────────────────────────────
  document.getElementById('colorSwatches').addEventListener('click', (e) => {
    const btn = e.target.closest('.swatch');
    if (!btn) return;

    document.querySelectorAll('.swatch').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');

    currentColor = btn.dataset.color;
    document.getElementById('colorPicker').value = currentColor;

    // Switch back to draw if we were erasing
    if (isErasing) activateDraw();
  });

  // ── Toolbar: custom colour picker ────────────────────────────────────────────
  document.getElementById('colorPicker').addEventListener('input', (e) => {
    currentColor = e.target.value;
    document.querySelectorAll('.swatch').forEach(s => s.classList.remove('active'));
    if (isErasing) activateDraw();
  });

  // ── Toolbar: brush size ──────────────────────────────────────────────────────
  document.getElementById('sizeOptions').addEventListener('click', (e) => {
    const btn = e.target.closest('.size-btn');
    if (!btn) return;
    document.querySelectorAll('.size-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    brushSize = parseInt(btn.dataset.size, 10);
  });

  // ── Toolbar: draw / erase ────────────────────────────────────────────────────
  function activateDraw() {
    isErasing = false;
    document.getElementById('btnDraw').classList.add('active');
    document.getElementById('btnErase').classList.remove('active');
    canvas.style.cursor = 'crosshair';
  }

  function activateErase() {
    isErasing = true;
    document.getElementById('btnErase').classList.add('active');
    document.getElementById('btnDraw').classList.remove('active');
    canvas.style.cursor = 'cell';
  }

  document.getElementById('btnDraw').addEventListener('click',  activateDraw);
  document.getElementById('btnErase').addEventListener('click', activateErase);

  // ── Toolbar: clear canvas ────────────────────────────────────────────────────
  document.getElementById('btnClear').addEventListener('click', () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Notify other clients
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'clear' }));
    }
  });

  // Also handle a 'clear' event from other clients
  const _origOnMessage = null;
  // We patch the clear-handling into ws.onmessage above via the type check

  // ── Window resize ────────────────────────────────────────────────────────────
  window.addEventListener('resize', resizeCanvas);

  // ── Init ─────────────────────────────────────────────────────────────────────
  resizeCanvas();
  connectWS();

})();