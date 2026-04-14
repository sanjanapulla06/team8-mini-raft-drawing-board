(function () 
{  'use strict';
  const PALETTE = ['#3b82f6','#8b5cf6','#ec4899','#10b981','#f59e0b','#06b6d4','#ef4444'];
  // user profile
  let MY_NAME  = '';
  let MY_COLOR = PALETTE[Math.floor(Math.random() * PALETTE.length)];
  let MY_ID    = Math.random().toString(36).slice(2, 8);
  // nmae modal
  const nameModalBg = document.getElementById('nameModalBg');
  const nameInput   = document.getElementById('nameInput');
  const nameSubmit  = document.getElementById('nameSubmit');
  const appView     = document.getElementById('appView');


  function submitName()
  {
    const val = nameInput.value.trim();
    if (!val) { nameInput.focus(); return; }
    MY_NAME = val;
    nameModalBg.style.display = 'none';
    appView.style.display     = 'flex';
    document.getElementById('myNameLabel').textContent = MY_NAME;
    WS.setClientId(MY_ID, MY_NAME, MY_COLOR);
    _initSelfAvatar();
    resizeCanvas();
    Logger.info(`Session started as "${MY_NAME}"`);
    window.toast(`Hello, ${MY_NAME}!`);
  }
  nameSubmit.addEventListener('click', submitName);
  nameInput.addEventListener('keydown', e => { if (e.key === 'Enter') submitName(); });
  nameInput.focus();

  // edit name
  document.getElementById('btnChangeName').addEventListener('click', () => 
    {
    const newName = prompt('Change your name:', MY_NAME);
    if (!newName || !newName.trim()) return;
    MY_NAME = newName.trim();
    document.getElementById('myNameLabel').textContent = MY_NAME;
    WS.setClientId(MY_ID, MY_NAME, MY_COLOR);
    const selfAvatar = document.querySelector('.peer-avatar[data-self]');
    if (selfAvatar) {
      selfAvatar.childNodes[0].textContent = MY_NAME.slice(0, 2);
      selfAvatar.querySelector('.tip').textContent = `You (${MY_NAME})`;
    }
    if (selfCursorEl) {
      const lbl = selfCursorEl.querySelector('.peer-cursor-label');
      if (lbl) lbl.textContent = MY_NAME;
    }
    Logger.info(`Name changed to "${MY_NAME}"`);
    window.toast(`Name updated to ${MY_NAME}`);
  });

// undo/redo buttons
  document.getElementById('btnUndo').addEventListener('click', () => {
    WS.sendControl({ type: 'undo' });
  });

  document.getElementById('btnRedo').addEventListener('click', () => {
    WS.sendControl({ type: 'redo' });
  });

  // setup 
  const canvas        = document.getElementById('canvas');
  const ctx           = canvas.getContext('2d');
  const previewCanvas = document.getElementById('previewCanvas');
  const pCtx          = previewCanvas.getContext('2d');


  function resizeCanvas()
  {
    const wrap = document.getElementById('canvasWrap');
    if (!wrap) return;
    const stage = document.querySelector('.stage');
    if (!stage) return;
    const stageRect = stage.getBoundingClientRect();
    const pad = 32;
    const w = Math.floor(stageRect.width  - pad);
    const h = Math.floor(stageRect.height - pad);
    if (w <= 10 || h <= 10) return;
    const snap = ctx.getImageData(0, 0, canvas.width, canvas.height);
    canvas.width        = w;
    canvas.height       = h;
    previewCanvas.width  = w;
    previewCanvas.height = h;
    ctx.putImageData(snap, 0, 0);
  }
  window.addEventListener('resize', resizeCanvas);

  //tools
  let brushMode  = 'pen';
  let shapeMode  = null;
  let color      = '#93c5fd';
  let size       = 2;
  let drawing    = false;
  let lastX      = null;
  let lastY      = null;
  let shapeStart = null;  
  const BRUSH_CONFIG = 
  {
    pen:         { alpha: 1.0,  composite: 'source-over', cap: 'round', sizeMultiplier: 1   },
    pencil:      { alpha: 0.85, composite: 'source-over', cap: 'round', sizeMultiplier: 1   },
    marker:      { alpha: 0.45, composite: 'source-over', cap: 'square', sizeMultiplier: 3  },
    highlighter: { alpha: 0.28, composite: 'source-over', cap: 'square', sizeMultiplier: 6  },
    eraser:      { alpha: 1.0,  composite: 'destination-out', cap: 'round', sizeMultiplier: 3 },
  };

        //draw
  function drawSeg(x0, y0, x1, y1, c, s, brush) 
  {
    const cfg = BRUSH_CONFIG[brush] || BRUSH_CONFIG.pen;
    const erase = brush === 'eraser';

    if (brush === 'pencil') {
      _drawPencilSeg(x0, y0, x1, y1, c, s);
      return;
    }

    ctx.save();
    ctx.globalAlpha              = cfg.alpha;
    ctx.globalCompositeOperation = erase ? 'destination-out' : cfg.composite;
    ctx.strokeStyle              = erase ? 'rgba(0,0,0,1)' : c;
    ctx.lineWidth                = s * cfg.sizeMultiplier;
    ctx.lineCap                  = cfg.cap;
    ctx.lineJoin                 = 'round';
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
    ctx.restore();
  }


  function _drawPencilSeg(x0, y0, x1, y1, c, s) 
  {
    const steps = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / 2));
    ctx.save();
    ctx.globalAlpha              = 0.55;
    ctx.globalCompositeOperation = 'source-over';
    ctx.strokeStyle              = c;
    ctx.lineWidth                = Math.max(1, s * 0.9);
    ctx.lineCap                  = 'round';

    for (let i = 0; i < steps; i++) 
    {
      const t   = i / steps;
      const px  = x0 + (x1 - x0) * t + (Math.random() - 0.5) * 1.2;
      const py  = y0 + (y1 - y0) * t + (Math.random() - 0.5) * 1.2;
      const px2 = x0 + (x1 - x0) * (t + 1 / steps) + (Math.random() - 0.5) * 1.2;
      const py2 = y0 + (y1 - y0) * (t + 1 / steps) + (Math.random() - 0.5) * 1.2;
      ctx.beginPath();
      ctx.moveTo(px, py);
      ctx.lineTo(px2, py2);
      ctx.stroke();
    }
    ctx.restore();
  }

 // default shapes
  function drawShape(shape, x0, y0, x1, y1, c, s, target, alpha) 
  {
    const tgt = target || ctx;
    tgt.save();
    tgt.globalAlpha              = alpha !== undefined ? alpha : 1;
    tgt.globalCompositeOperation = 'source-over';
    tgt.strokeStyle              = c;
    tgt.lineWidth                = s;
    tgt.lineCap                  = 'round';
    tgt.lineJoin                 = 'round';
    tgt.beginPath();
    switch (shape) 
    {
      case 'line':
        tgt.moveTo(x0, y0);
        tgt.lineTo(x1, y1);
        break;
      case 'rect':
        tgt.rect(x0, y0, x1 - x0, y1 - y0);
        break;
      case 'circle': 
      {
        const cx = (x0 + x1) / 2;
        const cy = (y0 + y1) / 2;
        const rx = Math.abs(x1 - x0) / 2;
        const ry = Math.abs(y1 - y0) / 2;
        tgt.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
        break;
      }
      case 'triangle': 
      {
        const mx = (x0 + x1) / 2;
        tgt.moveTo(mx, y0);
        tgt.lineTo(x1, y1);
        tgt.lineTo(x0, y1);
        tgt.closePath();
        break;
      }
    }

    tgt.stroke();
    tgt.restore();
  }

  // gateway - stroke
  WS.onStroke(function (stroke) 
  {
    if (stroke.shape) 
    {
      drawShape(stroke.shape, stroke.x0, stroke.y0, stroke.x, stroke.y, stroke.color, stroke.size);
    } 
    else 
    {
      const x0    = stroke.x0 !== undefined ? stroke.x0 : stroke.x;
      const y0    = stroke.y0 !== undefined ? stroke.y0 : stroke.y;
      drawSeg(x0, y0, stroke.x, stroke.y, stroke.color, stroke.size, stroke.brush || 'pen');
    }
  }
);

  WS.onSnapshot(function (strokes)
  {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    strokes.forEach((stroke) => {
      if (stroke.type === "snapshot-reset") return; 
      if (stroke.shape) 
      {
        drawShape(stroke.shape, stroke.x0, stroke.y0, stroke.x, stroke.y, stroke.color, stroke.size);
      } 
      else 
      {
        const x0 = stroke.x0 !== undefined ? stroke.x0 : stroke.x;
        const y0 = stroke.y0 !== undefined ? stroke.y0 : stroke.y;
        drawSeg(x0, y0, stroke.x, stroke.y, stroke.color, stroke.size, stroke.brush || 'pen');
      }
    });
  });


  WS.onSnapshotReset(function ()
  {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  });

  // pointe - x,y
  function getPos(e) 
  {
    const rect   = canvas.getBoundingClientRect();
    const scaleX = canvas.width  / rect.width;
    const scaleY = canvas.height / rect.height;
    const src    = e.touches ? e.touches[0] : e;
    return {
      x: (src.clientX - rect.left) * scaleX,
      y: (src.clientY - rect.top)  * scaleY,
      screenX: src.clientX,
      screenY: src.clientY
    };
  }

  // rAF Sends 
  let pending      = [];
  let rafScheduled = false;
  function flush() 
  {
    rafScheduled = false;
    pending.forEach(s => WS.sendStroke(s));
    pending = [];
  }
  function schedule() 
  {
    if (!rafScheduled) 
      { 
        rafScheduled = true; requestAnimationFrame(flush); 
      }
  }

  function onDown(e) 
  {
    e.preventDefault();
    drawing = true;
    const { x, y } = getPos(e);
    lastX = x; lastY = y;

    if (shapeMode) 
    {
      shapeStart = { x, y };
      previewCanvas.style.pointerEvents = 'auto';
      return;
    }
    drawSeg(x, y, x, y, color, size, brushMode);
    pending.push({ x, y, x0: x, y0: y, color, size, brush: brushMode, erase: brushMode === 'eraser' });
    schedule();
  }

// move
  function onMove(e) 
  {
    e.preventDefault();
    const { x, y, screenX, screenY } = getPos(e);
    document.getElementById('coordDisplay').textContent = `x: ${Math.round(x)}  y: ${Math.round(y)}`;
    _moveSelfCursor(screenX, screenY);

    if (!drawing) return;
    if (shapeMode && shapeStart) 
    {
      pCtx.clearRect(0, 0, previewCanvas.width, previewCanvas.height);
      drawShape(shapeMode, shapeStart.x, shapeStart.y, x, y, color, size, pCtx, 0.75);
      return;
    }
    drawSeg(lastX, lastY, x, y, color, size, brushMode);
    pending.push(
      { x, y, x0: lastX, y0: lastY, color, size, brush: brushMode, erase: brushMode === 'eraser' }
    );
    schedule();
    lastX = x; lastY = y;
  }


  function onUp(e) 
  {
    if (!drawing) return;
    drawing = false;

    if (shapeMode && shapeStart) 
    {
      const { x, y } = getPos(e);
      pCtx.clearRect(0, 0, previewCanvas.width, previewCanvas.height);
      previewCanvas.style.pointerEvents = 'none';
      // put shape on the main canvas
      drawShape(shapeMode, shapeStart.x, shapeStart.y, x, y, color, size);
      pending.push
      (
        {
          x, y,
          x0: shapeStart.x,
          y0: shapeStart.y,
          color, size,
          shape: shapeMode,
          brush: 'pen',
          erase: false
        }
      );
      schedule();
      shapeStart = null;
      return;
    }
    lastX = null; lastY = null;
  }


  function onLeave() 
  {
    if (drawing && !shapeMode) 
      { drawing = false; lastX = null; lastY = null; }
    _hideSelfCursor();
  }

  // events to both canvases
  [canvas, previewCanvas].forEach(c => 
  {
    c.addEventListener('mousedown',  onDown);
    c.addEventListener('mousemove',  onMove);
    c.addEventListener('mouseup',    onUp);
    c.addEventListener('mouseleave', onLeave);
    c.addEventListener('touchstart',  onDown, { passive: false });
    c.addEventListener('touchmove',   onMove, { passive: false });
    c.addEventListener('touchend',    onUp);
    c.addEventListener('touchcancel', onUp);
  }
);
  previewCanvas.style.pointerEvents = 'none';

  // my cursor pointer
  let selfCursorEl = null;
  function _ensureSelfCursor() 
  {
    if (selfCursorEl) return;
    selfCursorEl = _makeCursorEl(MY_NAME || 'You', MY_COLOR);
    document.getElementById('cursorLayer').appendChild(selfCursorEl);
  }
  function _moveSelfCursor(sx, sy) 
  {
    _ensureSelfCursor();
    selfCursorEl.style.left    = sx + 'px';
    selfCursorEl.style.top     = sy + 'px';
    selfCursorEl.style.opacity = '1';
  }
  function _hideSelfCursor() 
  {
    if (selfCursorEl) selfCursorEl.style.opacity = '0';
  }

  // other's cursors
  const peers = {};
  WS.onStroke(function (stroke) 
  {
    const peerId = stroke.clientId || `${stroke.peerName || 'peer'}:${stroke.peerColor || stroke.color || 'unknown'}`;
    if (!peerId || peerId === MY_ID) return;
    const peerName = stroke.peerName || 'Peer';
    const peerColor = stroke.peerColor || stroke.color || '#64748b';
    _updatePeerCursor(peerId, peerName, peerColor, null, null);
  }
);

  function _makeCursorEl(name, col) 
  {
    const el = document.createElement('div');
    el.className = 'peer-cursor';
    el.innerHTML = `
      <svg viewBox="0 0 20 20" fill="${col}" xmlns="http://www.w3.org/2000/svg">
        <path d="M4 2l13 8-6.5 1.5L8 18z" stroke="white" stroke-width="1"/>
      </svg>
      <div class="peer-cursor-label" style="background:${col}">${name}</div>
    `;
    el.style.opacity    = '0';
    el.style.transition = 'opacity .3s, left .06s linear, top .06s linear';
    return el;
  }

  function _updatePeerCursor(peerId, name, col, sx, sy) 
  {
    if (!peers[peerId]) 
    {
      const el = _makeCursorEl(name, col);
      document.getElementById('cursorLayer').appendChild(el);
      peers[peerId] = { name, color: col, el, hideTimer: null };
      _addPeerAvatar(peerId, name, col);
    }
    const peer = peers[peerId];
    if (sx !== null) peer.el.style.left = sx + 'px';
    if (sy !== null) peer.el.style.top  = sy + 'px';
    peer.el.style.opacity = '1';
    clearTimeout(peer.hideTimer);
    peer.hideTimer = setTimeout(() => { peer.el.style.opacity = '0'; }, 4000);
  }

  // other peer's profiles - avatars
  const _avatarIds = new Set();
  function _addPeerAvatar(peerId, name, col) 
  {
    if (_avatarIds.has(peerId)) return;
    _avatarIds.add(peerId);
    const container = document.getElementById('peerAvatars');
    if (!container) return;
    const el = document.createElement('div');
    el.className        = 'peer-avatar';
    el.style.background = col;
    el.dataset.peerId   = peerId;
    el.textContent      = name.slice(0, 2);
    el.innerHTML       += `<span class="tip">${name}</span>`;
    container.appendChild(el);
  }
  function _initSelfAvatar() 
  {
    const container = document.getElementById('peerAvatars');
    if (!container) return;
    const el = document.createElement('div');
    el.className        = 'peer-avatar';
    el.style.background = MY_COLOR;
    el.style.border     = '2px solid white';
    el.dataset.self     = 'true';
    el.textContent      = MY_NAME.slice(0, 2);
    el.innerHTML       += `<span class="tip">You (${MY_NAME})</span>`;
    container.insertAdjacentElement('afterbegin', el);
  }

  // tool bar
  function _clearBrushActive() 
  {
    document.querySelectorAll('#brushBtns .tool-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('btnErase').classList.remove('active');
  }
  function _clearShapeActive()
  {
    document.querySelectorAll('#shapeBtns .tool-btn').forEach(b => b.classList.remove('active'));
  }
  function _setCursor() 
  {
    if (shapeMode)              canvas.style.cursor = 'crosshair';
    else if (brushMode === 'eraser') canvas.style.cursor = 'cell';
    else                        canvas.style.cursor = 'crosshair';
  }

  document.getElementById('brushBtns').addEventListener('click', e => 
  {
    const btn = e.target.closest('[data-brush]');
    if (!btn) return;
    brushMode = btn.dataset.brush;
    shapeMode = null;
    _clearBrushActive();
    _clearShapeActive();
    btn.classList.add('active');
    _setCursor();
    Logger.info(`Brush: ${brushMode}`);
  }
);

  document.getElementById('btnErase').addEventListener('click', () => 
  {
    brushMode = 'eraser';
    shapeMode = null;
    _clearBrushActive();
    _clearShapeActive();
    document.getElementById('btnErase').classList.add('active');
    _setCursor();
  }
);

  document.getElementById('shapeBtns').addEventListener('click', e => 
  {
    const btn = e.target.closest('[data-shape]');
    if (!btn) return;
    const clicked = btn.dataset.shape;
    if (shapeMode === clicked) 
    {
      // Toggle off → back to pen
      shapeMode = null;
      brushMode = 'pen';
      _clearShapeActive();
      document.querySelector('#brushBtns [data-brush="pen"]').classList.add('active');
    } 
    else 
    {
      shapeMode = clicked;
      _clearBrushActive();
      _clearShapeActive();
      btn.classList.add('active');
    }
    _setCursor();
    Logger.info(`Shape: ${shapeMode || 'off'}`);
  }
);

  // color palette
  document.getElementById('swatches').addEventListener('click', e => 
  {
    const btn = e.target.closest('.swatch');
    if (!btn) return;
    document.querySelectorAll('.swatch').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    color = btn.dataset.color;
    document.getElementById('colorPicker').value = color;
    document.getElementById('customPreview').style.background = color;
  }
);

  document.getElementById('colorPicker').addEventListener('input', e => 
  {
    color = e.target.value;
    document.getElementById('customPreview').style.background = color;
    document.querySelectorAll('.swatch').forEach(s => s.classList.remove('active'));
  }
);

  document.getElementById('sizeBtns').addEventListener('click', e => 
  {
    const btn = e.target.closest('.size-btn');
    if (!btn) return;
    document.querySelectorAll('.size-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    size = parseInt(btn.dataset.size, 10);
  }
);

  //clear all
  document.getElementById('btnClear').addEventListener('click', () => 
  {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    Logger.info('Canvas cleared');
    window.toast('🧹 Canvas cleared');
  }
);

  // download
  function exportPNG() 
  {
    const off    = document.createElement('canvas');
    off.width    = canvas.width;
    off.height   = canvas.height;
    const offCtx = off.getContext('2d');
    offCtx.fillStyle = '#ffffff';
    offCtx.fillRect(0, 0, off.width, off.height);
    offCtx.drawImage(canvas, 0, 0);
    const a    = document.createElement('a');
    a.download = `raft-board-${Date.now()}.png`;
    a.href     = off.toDataURL('image/png');
    a.click();
    Logger.info('Canvas exported as PNG');
    window.toast('Downloaded!');
  }
  document.getElementById('btnDownload').addEventListener('click', exportPNG);

  // toast
  window.toast = function (msg, ms = 2600) 
  {
    const el = document.createElement('div');
    el.className   = 'toast';
    el.textContent = msg;
    document.getElementById('toastContainer').appendChild(el);
    setTimeout(() => {
      el.style.animation = 'toastOut .3s forwards';
      setTimeout(() => el.remove(), 300);
    }, ms);
  };

  // dark mode
  const themeBtn = document.getElementById('btnTheme');
  let isDark = false;
  function applyTheme(dark) 
  {
    isDark = dark;
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : '');
    themeBtn.textContent = dark ? 'L' : 'D';
    themeBtn.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
    localStorage.setItem('raft.theme', dark ? 'dark' : 'light');
  }

  const savedTheme = localStorage.getItem('raft.theme');
  if (savedTheme === 'dark') applyTheme(true);

  themeBtn.addEventListener('click', () => applyTheme(!isDark));

  // init
  document.getElementById('customPreview').style.background = color;

// resize
  requestAnimationFrame(() => requestAnimationFrame(resizeCanvas));

}
)
();