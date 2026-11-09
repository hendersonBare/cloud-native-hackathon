// Demo stage: loads one phone app per iframe, scales the frames to fit the
// window, and relays presenter controls (malicious, reset) to the phones.

import { initSwarm } from './swarm/index.js';
import { openStream } from './app/api.js';

const FRAME_W = 414;
const FRAME_H = 868;
const LABEL_H = 32; // device label + gap
const MIN_GAP = 96;
const SWARM_W = 380; // keep in sync with --swarm-w in swarm/swarm.css
const SWARM_GAP = 24;

const params = new URLSearchParams(location.search);
const mode = params.get('live') === '1' ? 'live' : 'mock';
const root = document.documentElement;
const toolbar = document.querySelector('.toolbar');

// Build each phone from the single frame template.
const template = document.getElementById('device-template');
const frames = [...document.querySelectorAll('.device[data-persona]')].map((device, i) => {
  const { persona, name, role } = device.dataset;
  device.append(template.content.cloneNode(true));
  const label = device.querySelector('.device-label');
  label.id = `device-label-${i}`;
  label.querySelector('strong').textContent = name;
  label.querySelector('span').textContent = ` · ${role}`;
  device.setAttribute('aria-labelledby', label.id);
  const frame = device.querySelector('iframe');
  frame.title = `${name}'s phone`;
  frame.dataset.persona = persona;
  return frame;
});
const malicious = document.getElementById('malicious');

function readPref(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function writePref(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage blocked */ }
}

function phoneUrl(persona) {
  const q = new URLSearchParams({ persona });
  if (mode === 'mock') q.set('mock', '1');
  return `phone.html?${q}`;
}

function post(msg) {
  for (const f of frames) f.contentWindow?.postMessage(msg, location.origin);
}

function fit() {
  const availH = window.innerHeight - toolbar.offsetHeight - 36 - LABEL_H;
  // The gap between the phones scales with --s too, so it counts inside the scaled width.
  const availW = window.innerWidth - 48;
  // The swarm panel is a fixed-width column between the phones; hidden, the layout is unchanged.
  const swarmEl = document.getElementById('swarm');
  const widthFit = swarmEl && !swarmEl.hidden
    ? (availW - SWARM_W - 2 * SWARM_GAP) / (2 * FRAME_W)
    : availW / (2 * FRAME_W + MIN_GAP);
  const s = Math.max(0.25, Math.min(1.3, availH / FRAME_H, widthFit));
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
    f.contentWindow?.postMessage({ type: 'config', malicious: malicious.checked }, location.origin);
  });
}

malicious.addEventListener('change', () => post({ type: 'config', malicious: malicious.checked }));

document.getElementById('reset-btn').addEventListener('click', async () => {
  if (mode === 'live') {
    try { await fetch('/api/demo/reset', { method: 'POST' }); } catch { /* gateway down */ }
  }
  for (const f of frames) f.src = phoneUrl(f.dataset.persona);
  swarm.reset();
});

const fsBtn = document.getElementById('fs-btn');
fsBtn.addEventListener('click', () => {
  const toggle = document.fullscreenElement ? document.exitFullscreen() : root.requestFullscreen?.();
  toggle?.catch((err) => console.warn('Full screen unavailable', err?.name || 'Error'));
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

// Swarm panel (web/swarm/): live mode reads the swarm SSE stream once here and relays the
// exchange events to the phones, which only receive their own persona stream from the gateway.
const swarm = initSwarm({
  root: document.getElementById('swarm'),
  toggle: document.getElementById('swarm-btn'),
  stage: document.getElementById('stage'),
  mode,
  openStream,
  onLayout: fit,
  relay: (event) => {
    if (event.type === 'exchange_message' || event.type === 'policy_decision') post({ type: 'gateway-swarm', event });
  },
});

window.addEventListener('resize', fit);
fit();
tickClock();
setInterval(tickClock, 15000);
