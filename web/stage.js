// Demo stage: loads one phone app per iframe, scales the frames to fit the
// window, and relays presenter controls (theme, malicious, reset) to the phones.

const FRAME_W = 414;
const FRAME_H = 868;
const LABEL_H = 32; // device label + gap
const MIN_GAP = 96;

const params = new URLSearchParams(location.search);
const mode = params.get('live') === '1' ? 'live' : 'mock';
const root = document.documentElement;
const toolbar = document.querySelector('.toolbar');
const frames = [...document.querySelectorAll('iframe[data-persona]')];
const themeBtn = document.getElementById('theme-btn');
const malicious = document.getElementById('malicious');

function readPref(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function writePref(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage blocked */ }
}

// Light is the demo default; the toolbar button switches for this browser only.
let theme = params.get('theme') || readPref('rapport.theme', 'light');

function phoneUrl(persona) {
  const q = new URLSearchParams({ persona, theme });
  if (mode === 'mock') q.set('mock', '1');
  return `phone.html?${q}`;
}

function post(msg) {
  for (const f of frames) f.contentWindow?.postMessage(msg, location.origin);
}

function applyTheme() {
  root.dataset.theme = theme;
  themeBtn.textContent = theme === 'dark' ? 'Light theme' : 'Dark theme';
  themeBtn.setAttribute('aria-pressed', String(theme === 'light'));
  post({ type: 'theme', theme });
}

function fit() {
  const availH = window.innerHeight - toolbar.offsetHeight - 36 - LABEL_H;
  const availW = window.innerWidth - 48 - MIN_GAP;
  const s = Math.max(0.25, Math.min(1.3, availH / FRAME_H, availW / (2 * FRAME_W)));
  root.style.setProperty('--s', s.toFixed(4));
}

function tickClock() {
  const now = new Date();
  const t = `${now.getHours() % 12 || 12}:${String(now.getMinutes()).padStart(2, '0')}`;
  for (const el of document.querySelectorAll('.sb-time')) el.textContent = t;
}

const badge = document.getElementById('mode-badge');
badge.textContent = mode === 'mock' ? 'Mock mode' : 'Live';
badge.dataset.mode = mode;

for (const f of frames) {
  f.src = phoneUrl(f.dataset.persona);
  f.addEventListener('load', () => {
    f.contentWindow?.postMessage({ type: 'theme', theme }, location.origin);
    f.contentWindow?.postMessage({ type: 'config', malicious: malicious.checked }, location.origin);
  });
}

themeBtn.addEventListener('click', () => {
  theme = theme === 'dark' ? 'light' : 'dark';
  writePref('rapport.theme', theme);
  applyTheme();
});

malicious.addEventListener('change', () => post({ type: 'config', malicious: malicious.checked }));

document.getElementById('reset-btn').addEventListener('click', async () => {
  if (mode === 'live') {
    try { await fetch('/api/demo/reset', { method: 'POST' }); } catch { /* gateway down */ }
  }
  for (const f of frames) f.src = phoneUrl(f.dataset.persona);
});

const fsBtn = document.getElementById('fs-btn');
fsBtn.addEventListener('click', () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else root.requestFullscreen?.();
});
document.addEventListener('fullscreenchange', () => {
  const on = !!document.fullscreenElement;
  fsBtn.textContent = on ? 'Exit full screen' : 'Full screen';
  fsBtn.setAttribute('aria-label', on ? 'Exit full screen' : 'Enter full screen');
});

// Collapse / expand the presenter bar (remembered per browser).
const hideBtn = document.getElementById('hide-btn');
const showBtn = document.getElementById('show-btn');
function setControls(visible, moveFocus) {
  document.body.classList.toggle('controls-hidden', !visible);
  showBtn.hidden = visible;
  hideBtn.setAttribute('aria-expanded', String(visible));
  writePref('rapport.controls', visible ? 'shown' : 'hidden');
  fit();
  if (moveFocus) (visible ? hideBtn : showBtn).focus();
}
hideBtn.addEventListener('click', () => setControls(false, true));
showBtn.addEventListener('click', () => setControls(true, true));
setControls(readPref('rapport.controls', 'shown') !== 'hidden', false);

window.addEventListener('resize', fit);
applyTheme();
fit();
tickClock();
setInterval(tickClock, 15000);
