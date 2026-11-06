'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const root = document.documentElement;
  const canvas = $('acid-canvas');
  const ctx = canvas.getContext('2d');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let fxWanted = true, clicks = 0;
  try { fxWanted = localStorage.getItem('benis.fx') !== 'off'; clicks = Math.max(0, Math.min(999999999, Number(localStorage.getItem('benis.clicks')) || 0)); } catch (_) {}
  let fx = fxWanted && !reduced.matches, raf = 0, width = 0, height = 0, tick = 0;
  let lastDraw = 0, lastStats = 0, lastLetter = 0, terminalLine = '', letter = 0, queuedLines = [];
  let warpTimer = 0, chaosTimer = 0, toastTimer = 0, debrisTimer = 0;
  const pointer = {x: .5, y: .4, tx: .5, ty: .4};
  const palette = ['215,255,0', '255,53,204', '41,241,255'];
  const sparks = Array.from({length: 20}, (_, i) => ({x: (i * .6180339) % 1, y: (i * .3721) % 1, size: 1 + (i % 3)}));
  const thoughts = [
    ['COSMIC\nBENIS', 'Совет пикселей одобряет с лёгким недоумением.'],
    ['BENIS\nOVERDRIVE', 'Такого количества бениса в смете не было.'],
    ['PURPOSE\nNOT FOUND', 'Поиски смысла приостановлены за ненадобностью.'],
    ['LONG\nBENIS', 'Теперь на 37% длиннее. Методика засекречена.'],
    ['ACID\nDEPARTMENT', 'Специалист ушёл за кофе в соседнее измерение.'],
    ['HAHA\nWHAT', 'Всё работает. Что именно — пока непонятно.'],
    ['BENIS\nINFINITY', 'Ваш запрос очень важен для совета пустоты.'],
    ['ПИКСЕЛИ\nУСТАЛИ', 'Рекомендуется срочно нажать ещё что-нибудь.']
  ];
  const logs = [
    'locating the funny button... FOUND', 'compiling ancient benis protocol... OK',
    'signal smells like purple. investigating.', 'human approval: scientifically questionable',
    'nonsense buffer: unexpectedly full', 'reality check returned undefined',
    'warning: purpose has left the building', 'deploying additional unnecessary pixels',
    'connection to parallel universe: probably', 'all systems completely unserious'
  ];
  const store = (key, value) => { try { localStorage.setItem(key, String(value)); } catch (_) {} };
  function clock() { $('clock').textContent = new Date().toLocaleTimeString('ru-RU', {hour12: false}); }
  function count() { clicks++; $('clickCount').textContent = String(clicks).padStart(6, '0'); store('benis.clicks', clicks); }
  function toast(text) { clearTimeout(toastTimer); $('toast').textContent = text; $('toast').classList.add('visible'); toastTimer = setTimeout(() => $('toast').classList.remove('visible'), 2700); }
  function line(text) {
    const paragraph = document.createElement('p');
    const stamp = document.createElement('span');
    stamp.textContent = new Date().toLocaleTimeString('ru-RU', {minute: '2-digit', second: '2-digit'});
    paragraph.append(stamp, document.createTextNode(text));
    $('terminalLines').append(paragraph);
    while ($('terminalLines').children.length > 6) $('terminalLines').firstElementChild.remove();
    return paragraph;
  }
  function queue(text) { if (!fx) { line(text); return; } queuedLines.push(text); if (queuedLines.length > 6) queuedLines.shift(); }
  let activeLine = null;
  function type(now) {
    if (now - lastLetter < 32) return;
    lastLetter = now;
    if (!activeLine && queuedLines.length) { terminalLine = queuedLines.shift(); letter = 0; activeLine = line(''); }
    if (activeLine) { activeLine.lastChild.textContent = terminalLine.slice(0, ++letter); if (letter >= terminalLine.length) activeLine = null; }
  }
  function reroll() {
    count(); const item = thoughts[Math.floor(Math.random() * thoughts.length)];
    $('chaos').textContent = item[0]; $('council').textContent = item[1]; $('approval').textContent = Math.floor(20 + Math.random() * 80) + '%';
    queue('benis recalibrated. emotional damage: minimal.');
  }
  function resize() {
    width = window.innerWidth; height = window.innerHeight;
    const scale = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale);
    if (ctx) ctx.setTransform(scale, 0, 0, scale, 0, 0);
    if (!fx && ctx) draw(0);
  }
  function draw(delta) {
    if (!ctx) return;
    tick += delta;
    pointer.x += (pointer.tx - pointer.x) * .045; pointer.y += (pointer.ty - pointer.y) * .045;
    ctx.fillStyle = 'rgba(9,5,18,.20)'; ctx.fillRect(0, 0, width, height);
    for (let i = 0; i < 7; i++) {
      const x = width * (.06 + i * .15) + Math.sin(tick * .65 + i) * 45 + (pointer.x - .5) * 45;
      const y = height * (.14 + ((i * .27) % .75)) + Math.cos(tick * .45 + i * 1.9) * 38 + (pointer.y - .5) * 30;
      const radius = Math.min(180, width * .2) + Math.sin(tick + i) * 20;
      const gradient = ctx.createRadialGradient(x, y, 0, x, y, Math.max(1, radius));
      gradient.addColorStop(0, 'rgba(' + palette[i % 3] + ',.075)'); gradient.addColorStop(1, 'rgba(9,5,18,0)');
      ctx.fillStyle = gradient; ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
    }
    ctx.lineWidth = .6;
    for (let i = 0; i < 5; i++) {
      ctx.strokeStyle = 'rgba(' + palette[i % 3] + ',.11)'; ctx.beginPath();
      const y = height * (.1 + i * .2);
      ctx.moveTo(-30, y); ctx.bezierCurveTo(width * .25, y + Math.sin(tick + i) * 130, width * .75, y - Math.cos(tick * .7 + i) * 120, width + 30, y + 30); ctx.stroke();
    }
    for (const spark of sparks) {
      const x = (spark.x * width + Math.sin(tick * .4 + spark.y * 9) * 22 + width) % width;
      const y = (spark.y * height - tick * (3 + spark.size) + height * 100) % height;
      ctx.fillStyle = 'rgba(213,255,151,.25)'; ctx.fillRect(x, y, spark.size, spark.size);
    }
  }
  function frame(now) {
    raf = 0;
    if (!fx || document.hidden) return;
    if (now - lastDraw >= 1000 / 30) {
      const delta = Math.min(.06, (now - lastDraw) / 1000 || .03); lastDraw = now; draw(delta); type(now);
      if (now - lastStats > 1900) { lastStats = now; $('signalValue').textContent = (79 + Math.random() * 20).toFixed(1) + '%'; if (queuedLines.length < 2) queuedLines.push(logs[Math.floor(Math.random() * logs.length)]); }
    }
    raf = requestAnimationFrame(frame);
  }
  function syncFx() {
    fx = fxWanted && !reduced.matches;
    root.dataset.fx = fx ? 'on' : 'off'; $('fxToggle').setAttribute('aria-pressed', String(fx));
    $('fxToggle').textContent = reduced.matches ? 'FX: ТИХО' : 'FX: ' + (fx ? 'ВКЛ' : 'ВЫКЛ');
    $('fxToggle').disabled = reduced.matches; $('fxToggle').title = reduced.matches ? 'Движение ограничено настройкой устройства' : 'Остановить или включить анимацию';
    if (raf) cancelAnimationFrame(raf); raf = 0;
    if (fx && !document.hidden) raf = requestAnimationFrame(frame);
    else if (ctx) { ctx.clearRect(0, 0, width, height); draw(0); }
    if (!fx) { $('debris').replaceChildren(); document.body.classList.remove('warping', 'chaotic'); }
  }
  function confetti() {
    if (!fx) return;
    clearTimeout(debrisTimer); const fragment = document.createDocumentFragment();
    const words = ['✳', '404', 'BENIS', '¿', '↗', '+'];
    for (let i = 0; i < 18; i++) {
      const bit = document.createElement('span'); bit.className = 'debris-bit'; bit.textContent = words[i % words.length];
      bit.style.setProperty('--dx', ((Math.random() - .5) * Math.min(width, 900)) + 'px');
      bit.style.setProperty('--dy', ((Math.random() - .65) * Math.min(height, 700)) + 'px');
      bit.style.setProperty('--rotate', ((Math.random() - .5) * 300) + 'deg'); fragment.append(bit);
    }
    $('debris').replaceChildren(fragment); debrisTimer = setTimeout(() => $('debris').replaceChildren(), 1200);
  }
  $('warpBtn').addEventListener('click', () => { count(); queue('WARP DRIVE: engaged. dignity: ejected.'); toast('ПРОСТРАНСТВО ВРЕМЕННО НЕ СОГЛАСНО.'); if (fx) { clearTimeout(warpTimer); document.body.classList.remove('warping'); void document.body.offsetWidth; document.body.classList.add('warping'); warpTimer = setTimeout(() => document.body.classList.remove('warping'), 1250); confetti(); } });
  $('shuffleBtn').addEventListener('click', reroll);
  $('benisBtn').addEventListener('click', () => { reroll(); confetti(); toast('ЧТО-ТО ПРОИЗОШЛО. ДОКАЗАТЬ НЕВОЗМОЖНО.'); });
  $('nukeBtn').addEventListener('click', () => { count(); clearTimeout(chaosTimer); if (fx) { document.body.classList.add('chaotic'); chaosTimer = setTimeout(() => document.body.classList.remove('chaotic'), 5000); confetti(); } queue('DO NOT PRESS button pressed. of course.'); $('footerNote').textContent = 'СОВЕТ ПИКСЕЛЕЙ ВЫРАЖАЕТ ОЗАБОЧЕННОСТЬ.'; toast('МЫ ЖЕ ПРОСИЛИ. ЛАДНО, ЕЩЁ РАЗ МОЖНО.'); });
  $('fxToggle').addEventListener('click', () => { fxWanted = !fxWanted; store('benis.fx', fxWanted ? 'on' : 'off'); syncFx(); });
  $('tuner').addEventListener('input', event => { const value = Number(event.target.value); $('tunerValue').textContent = value + '%'; $('frequency').textContent = (69 + value * .47).toFixed(2) + ' Hz'; root.style.setProperty('--hue', String(value * 1.8)); });
  window.addEventListener('resize', resize, {passive: true});
  window.addEventListener('pointermove', event => { pointer.tx = event.clientX / Math.max(1, width); pointer.ty = event.clientY / Math.max(1, height); }, {passive: true});
  document.addEventListener('visibilitychange', syncFx); reduced.addEventListener('change', syncFx);
  $('clickCount').textContent = String(clicks).padStart(6, '0'); $('year').textContent = String(new Date().getFullYear());
  clock(); setInterval(clock, 1000); resize(); syncFx(); queue('HAHA BENIS SYSTEMS: transmission established.');
})();
