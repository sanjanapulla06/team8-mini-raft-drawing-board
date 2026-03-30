
(function () {
  'use strict';

  //  color
  const PALETTE = ['#3b82f6','#8b5cf6','#ec4899','#10b981','#f59e0b','#06b6d4','#ef4444'];

//  naming ppl like canva
  let MY_NAME  = '';
  let MY_COLOR = PALETTE[Math.floor(Math.random() * PALETTE.length)];
  let MY_ID    = Math.random().toString(36).slice(2, 8);

  const nameModalBg = document.getElementById('nameModalBg');
  const nameInput   = document.getElementById('nameInput');
  const nameSubmit  = document.getElementById('nameSubmit');
  const appView     = document.getElementById('appView');

  function submitName() {
    const val = nameInput.value.trim();
    if (!val) { nameInput.focus(); return; }
    MY_NAME = val;
    nameModalBg.style.display = 'none';
    appView.style.display     = 'flex';
    document.getElementById('myNameLabel').textContent = MY_NAME;
    _initSelfAvatar();
    resizeCanvas();
    Logger.info(`Session started as "${MY_NAME}"`);
    window.toast(`Hello, ${MY_NAME}!`);
  }

  nameSubmit.addEventListener('click', submitName);
  nameInput.addEventListener('keydown', e => { if (e.key === 'Enter') submitName(); });
  nameInput.focus();

  // profile - user
  document.getElementById('btnChangeName').addEventListener('click', () => {
    const newName = prompt('Change your name:', MY_NAME);
    if (!newName || !newName.trim()) return;
    MY_NAME = newName.trim();
    document.getElementById('myNameLabel').textContent = MY_NAME;
    // Update self avatar
    const selfAvatar = document.querySelector('.peer-avatar[data-self]');
    if (selfAvatar) {
      selfAvatar.childNodes[0].textContent = MY_NAME.slice(0, 2);
      selfAvatar.querySelector('.tip').textContent = `You (${MY_NAME})`;
    }
    // Update self cursor label
    if (selfCursorEl) {
      const lbl = selfCursorEl.querySelector('.peer-cursor-label');
      if (lbl) lbl.textContent = MY_NAME;
    }
    Logger.info(`Name changed to "${MY_NAME}"`);
    window.toast(`✏️ Name updated to ${MY_NAME}`);
  });

// drawing boarf
  const canvas = document.getElementById('canvas');
  const ctx    = canvas.getContext('2d');

  function resizeCanvas() {
    const stage = document.querySelector('.stage');
    if (!stage) return;
    const pad  = 40;
    const snap = ctx.getImageData(0, 0, canvas.width, canvas.height);
    canvas.width  = Math.floor(Math.min(stage.clientWidth  - pad, 1280));
    canvas.height = Math.floor(Math.min(stage.clientHeight - pad, 860));
    ctx.putImageData(snap, 0, 0);
  }
  window.addEventListener('resize', resizeCanvas);

  let drawing   = false;
  let color     = '#93c5fd';
  let size      = 2;
  let isErasing = false;
  let lastX     = null;
  let lastY     = null;

  function drawSeg(x0, y0, x1, y1, c, s, erase) {
    ctx.save();
    ctx.globalCompositeOperation = erase ? 'destination-out' : 'source-over';
    ctx.strokeStyle = erase ? 'rgba(0,0,0,1)' : c;
    ctx.lineWidth   = s;
    ctx.lineCap     = 'round';
    ctx.lineJoin    = 'round';
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
    ctx.restore();
  }

// logs
  WS.onStroke(function (stroke) {
    const x0    = stroke.x0 !== undefined ? stroke.x0 : stroke.x;
    const y0    = stroke.y0 !== undefined ? stroke.y0 : stroke.y;
    const erase = stroke.type === 'erase';
    drawSeg(x0, y0, stroke.x, stroke.y, stroke.color, stroke.size, erase);
  });

//  cursor x,y
  function getPos(e) {
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

//  raf 
  let pending      = [];
  let rafScheduled = false;

  function flush() {
    rafScheduled = false;
    pending.forEach(s => WS.sendStroke(s));
    pending = [];
  }
  function schedule() {
    if (!rafScheduled) { rafScheduled = true; requestAnimationFrame(flush); }
  }

  function onDown(e) {
    e.preventDefault();
    drawing = true;
    const { x, y } = getPos(e);
    lastX = x; lastY = y;
    drawSeg(x, y, x, y, color, size, isErasing);
    pending.push({ x, y, x0: x, y0: y, color, size, erase: isErasing });
    schedule();
  }

  function onMove(e) {
    e.preventDefault();
    const { x, y, screenX, screenY } = getPos(e);
    document.getElementById('coordDisplay').textContent = `x: ${Math.round(x)}  y: ${Math.round(y)}`;
    _moveSelfCursor(screenX, screenY);
    if (!drawing) return;
    drawSeg(lastX, lastY, x, y, color, size, isErasing);
    pending.push({ x, y, x0: lastX, y0: lastY, color, size, erase: isErasing });
    schedule();
    lastX = x; lastY = y;
  }

  function onUp()    { drawing = false; lastX = null; lastY = null; }
  function onLeave() { drawing = false; _hideSelfCursor(); }

  canvas.addEventListener('mousedown',  onDown);
  canvas.addEventListener('mousemove',  onMove);
  canvas.addEventListener('mouseup',    onUp);
  canvas.addEventListener('mouseleave', onLeave);
  canvas.addEventListener('touchstart',  onDown, { passive: false });
  canvas.addEventListener('touchmove',   onMove, { passive: false });
  canvas.addEventListener('touchend',    onUp);
  canvas.addEventListener('touchcancel', onUp);

//  mu cursor
  let selfCursorEl = null;

  function _ensureSelfCursor() {
    if (selfCursorEl) return;
    selfCursorEl = _makeCursorEl(MY_NAME || 'You', MY_COLOR);
    document.getElementById('cursorLayer').appendChild(selfCursorEl);
  }
  function _moveSelfCursor(sx, sy) {
    _ensureSelfCursor();
    selfCursorEl.style.left    = sx + 'px';
    selfCursorEl.style.top     = sy + 'px';
    selfCursorEl.style.opacity = '1';
  }
  function _hideSelfCursor() {
    if (selfCursorEl) selfCursorEl.style.opacity = '0';
  }

//   other cursor
  const peers = {};

  WS.onStroke(function (stroke) {
    if (stroke.color === color && !isErasing) return;
    const peerId = stroke.color;
    _updatePeerCursor(peerId, stroke.color, stroke.color, null, null);
  });

  function _makeCursorEl(name, col) {
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

  function _updatePeerCursor(peerId, name, col, sx, sy) {
    if (!peers[peerId]) {
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

  const _avatarIds = new Set();

  function _addPeerAvatar(peerId, name, col) {
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

  function _initSelfAvatar() {
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

  // color palette
  document.getElementById('swatches').addEventListener('click', e => {
    const btn = e.target.closest('.swatch');
    if (!btn) return;
    document.querySelectorAll('.swatch').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    color = btn.dataset.color;
    document.getElementById('colorPicker').value = color;
    document.getElementById('customPreview').style.background = color;
    if (isErasing) activateDraw();
  });

  document.getElementById('colorPicker').addEventListener('input', e => {
    color = e.target.value;
    document.getElementById('customPreview').style.background = color;
    document.querySelectorAll('.swatch').forEach(s => s.classList.remove('active'));
    if (isErasing) activateDraw();
  });

//  brush thickness
  document.getElementById('sizeBtns').addEventListener('click', e => {
    const btn = e.target.closest('.size-btn');
    if (!btn) return;
    document.querySelectorAll('.size-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    size = parseInt(btn.dataset.size, 10);
  });

//  eraser
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

//   delete full
  document.getElementById('btnClear').addEventListener('click', () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    Logger.info('Canvas cleared');
    window.toast('🧹 Canvas cleared');
  });

//  download n save 
  function exportPNG() {
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
    window.toast('🖼️ Downloaded!');
  }
  document.getElementById('btnDownload').addEventListener('click', exportPNG);

// // keyboard shorcuts we need??
//   document.addEventListener('keydown', e => {
//     if (e.target.tagName === 'INPUT') return;
//     if (e.key === 'd' || e.key === 'D') activateDraw();
//     if (e.key === 'e' || e.key === 'E') activateErase();
//     if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); exportPNG(); }
//   });

  window.toast = function (msg, ms = 2600) {
    const el = document.createElement('div');
    el.className   = 'toast';
    el.textContent = msg;
    document.getElementById('toastContainer').appendChild(el);
    setTimeout(() => {
      el.style.animation = 'toastOut .3s forwards';
      setTimeout(() => el.remove(), 300);
    }, ms);
  };

// init
  document.getElementById('customPreview').style.background = color;

})();