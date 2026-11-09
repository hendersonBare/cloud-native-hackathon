// Phone app entry: theme, per-phone store, hash router.
// URL: phone.html?persona=acme.ava&theme=dark&mock=1#/home

import { person, peerOf, VIEWS } from './data.js';
import * as bus from './bus.js';
import { initFlow } from './flow.js';
import { parseHash, hashFor } from './route.js';

const params = new URLSearchParams(location.search);
const meId = person(params.get('persona')) ? params.get('persona') : 'acme.ava';
const mode = params.get('mock') === '1' ? 'mock' : 'live';
bus.setSelf(meId);

// Per-phone state that survives navigation (screens keep their slice under their name).
const store = { config: { malicious: false } };

const app = document.getElementById('app');
const overlay = document.getElementById('overlay');
const root = document.documentElement;
let theme = params.get('theme') === 'dark' ? 'dark' : 'light';

function setTheme(t) {
  theme = t === 'light' ? 'light' : 'dark';
  root.className = theme === 'light' ? 'rp rp-light' : 'rp';
  root.style.colorScheme = theme;
  bus.emitLocal('theme', theme);
}
setTheme(theme);
root.lang = person(meId).lang || 'en';

// Messages from the stage (index.html).
window.addEventListener('message', (e) => {
  if (e.origin !== location.origin || !e.data) return;
  if (e.data.type === 'theme') setTheme(e.data.theme);
  if (e.data.type === 'config') {
    store.config.malicious = !!e.data.malicious;
    bus.emitLocal('config', store.config);
  }
});

export function go(name, params) {
  location.hash = hashFor(name, params);
}

const cssLoaded = new Set();
function ensureCss(name) {
  if (cssLoaded.has(name)) return;
  cssLoaded.add(name);
  document.head.append(Object.assign(document.createElement('link'), { rel: 'stylesheet', href: `app/screens/${name}.css` }));
}

let cleanups = [];
let renderToken = 0;

function makeCtx(route) {
  return {
    me: person(meId),
    peer: person(peerOf(meId)),
    person,
    view: VIEWS[meId] || {},
    store,
    mode,
    get theme() { return theme; },
    route,
    go,
    bus,
    overlay,
    onCleanup(fn) { cleanups.push(fn); },
  };
}

async function show(focus) {
  const token = ++renderToken;
  const route = parseHash(location.hash);
  ensureCss(route.name);
  let mod;
  try {
    mod = await import(`./screens/${route.name}.js`);
  } catch (err) {
    console.error(`screen ${route.name} failed to load`, err?.name || 'Error');
    return;
  }
  if (token !== renderToken) return;
  for (const fn of cleanups) { try { fn(); } catch { /* ignore */ } }
  cleanups = [];
  const el = mod.render(makeCtx(route));
  app.replaceChildren(el);
  if (focus) {
    const target = el.querySelector('h1') || el;
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    target.focus({ preventScroll: true });
  }
}

function showSafely(focus) {
  show(focus).catch((err) => console.error('screen render failed', err?.name || 'Error'));
}

window.addEventListener('hashchange', () => showSafely(true));
initFlow({ me: person(meId), peer: person(peerOf(meId)), store, mode, go, bus, overlay });
showSafely(false);
