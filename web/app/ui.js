// Tiny DOM helpers shared by every screen. Text always goes in as text nodes,
// never as HTML, so server and counterparty strings can't inject markup.

const SVG_NS = 'http://www.w3.org/2000/svg';

function setStyle(el, style) {
  for (const [k, v] of Object.entries(style)) {
    if (v == null) continue;
    if (k.startsWith('--') || k.includes('-')) el.style.setProperty(k, String(v));
    else el.style[k] = v;
  }
}

function appendChildren(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false || c === true) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

/**
 * h('button', { class: 'btn', onClick: fn, 'aria-label': 'Close' }, 'Text', childEl)
 * - `class`, `style` (object or string), `dataset`, on<Event> handlers, boolean attrs.
 */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  applyAttrs(el, attrs);
  appendChildren(el, children);
  return el;
}

function applyAttrs(el, attrs) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.setAttribute('class', v);
    else if (k === 'style') {
      if (typeof v === 'string') el.setAttribute('style', v);
      else setStyle(el, v);
    } else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, String(v));
  }
}

/** Build an SVG from a spec: svg([['path', { d: '...' }], ['circle', { cx: 12, cy: 12, r: 4 }]], opts) */
export function svg(spec, { size = 22, stroke = 1.7, fill = 'none', viewBox = '0 0 24 24', label, round = true } = {}) {
  const el = document.createElementNS(SVG_NS, 'svg');
  el.setAttribute('width', size);
  el.setAttribute('height', size);
  el.setAttribute('viewBox', viewBox);
  el.setAttribute('fill', fill);
  el.setAttribute('stroke', fill === 'none' ? 'currentColor' : 'none');
  el.setAttribute('stroke-width', stroke);
  if (round) {
    el.setAttribute('stroke-linecap', 'round');
    el.setAttribute('stroke-linejoin', 'round');
  }
  if (label) {
    el.setAttribute('role', 'img');
    el.setAttribute('aria-label', label);
  } else {
    el.setAttribute('aria-hidden', 'true');
  }
  for (const [tag, attrs] of spec) {
    const child = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) child.setAttribute(k, v);
    el.append(child);
  }
  return el;
}

const DOT = { fill: 'currentColor', stroke: 'none' };

export const ICONS = {
  home: [['path', { d: 'M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z' }]],
  mic: [['rect', { x: 9, y: 3, width: 6, height: 11, rx: 3 }], ['path', { d: 'M5 11a7 7 0 0 0 14 0M12 18v3' }]],
  memory: [['path', { d: 'm12 3 9 5-9 5-9-5z' }], ['path', { d: 'm3 13 9 5 9-5' }]],
  calendar: [['rect', { x: 3, y: 5, width: 18, height: 16, rx: 2 }], ['path', { d: 'M3 10h18M8 3v4M16 3v4' }]],
  people: [['circle', { cx: 9, cy: 12, r: 5.5 }], ['circle', { cx: 15, cy: 12, r: 5.5 }]],
  back: [['path', { d: 'm15 6-6 6 6 6' }]],
  chevron: [['path', { d: 'm9 6 6 6-6 6' }]],
  close: [['path', { d: 'M6 6l12 12M18 6 6 18' }]],
  check: [['path', { d: 'm5 12 5 5 9-10' }]],
  search: [['circle', { cx: 11, cy: 11, r: 7 }], ['path', { d: 'm20 20-3.5-3.5' }]],
  user: [['circle', { cx: 12, cy: 8, r: 4 }], ['path', { d: 'M4 21a8 8 0 0 1 16 0' }]],
  lock: [['rect', { x: 5, y: 11, width: 14, height: 10, rx: 2 }], ['path', { d: 'M8 11V7a4 4 0 0 1 8 0v4' }]],
  agent: [['circle', { cx: 12, cy: 12, r: 8 }], ['circle', { cx: 12, cy: 12, r: 2.6, ...DOT }]],
  more: [['circle', { cx: 5, cy: 12, r: 1.6, ...DOT }], ['circle', { cx: 12, cy: 12, r: 1.6, ...DOT }], ['circle', { cx: 19, cy: 12, r: 1.6, ...DOT }]],
  stop: [['rect', { x: 6, y: 6, width: 12, height: 12, rx: 2.5, ...DOT }]],
  plus: [['path', { d: 'M12 5v14M5 12h14' }]],
  upload: [['path', { d: 'M12 16V4M7 9l5-5 5 5M5 20h14' }]],
  file: [['path', { d: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z' }], ['path', { d: 'M14 3v5h5' }]],
  edit: [['path', { d: 'M4 20h4L19 9l-4-4L4 16z' }], ['path', { d: 'm13.5 6.5 4 4' }]],
  shield: [['path', { d: 'M12 3 5 6v6c0 4.4 3 7.6 7 9 4-1.4 7-4.6 7-9V6z' }]],
  sparkle: [['path', { d: 'M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6' }]],
  clock: [['circle', { cx: 12, cy: 12, r: 8.5 }], ['path', { d: 'M12 7.5V12l3 2' }]],
};

export function icon(name, opts = {}) {
  const spec = ICONS[name];
  if (!spec) throw new Error(`unknown icon: ${name}`);
  return svg(spec, opts);
}

/** Initials avatar. tone: gold | steel | sage | lilac */
export function avatar(initials, tone = 'steel', size = 44, fontSize) {
  return h('span', {
    class: `avatar tone-${tone}`,
    'aria-hidden': 'true',
    style: { width: `${size}px`, height: `${size}px`, fontSize: `${fontSize || Math.round(size * 0.34)}px` },
  }, initials);
}

/** The user's own agent mark (gold ring with a dot). */
export function agentMark(size = 42, iconSize) {
  return h('span', {
    class: 'avatar tone-gold',
    'aria-hidden': 'true',
    style: { width: `${size}px`, height: `${size}px` },
  }, icon('agent', { size: iconSize || Math.round(size * 0.5) }));
}

export const TABS = [
  { route: 'home', label: 'Home', icon: 'home' },
  { route: 'live', label: 'Capture', icon: 'mic' },
  { route: 'memory', label: 'Memory', icon: 'memory' },
  { route: 'calendar', label: 'Calendar', icon: 'calendar' },
  { route: 'people', label: 'People', icon: 'people' },
];

/** Which tab is highlighted for each route. */
export const TAB_FOR = {
  home: 'home', profile: 'home',
  live: 'live', tag: 'live',
  memory: 'memory',
  calendar: 'calendar',
  people: 'people', person: 'people', exchange: 'people', match: 'people',
};

export function bottomNav(active) {
  const current = TAB_FOR[active] || active;
  return h('nav', { class: 'bottom-nav', 'aria-label': 'Main' },
    h('div', { class: 'bar' },
      TABS.map((t) => h('a', {
        href: `#/${t.route}`,
        'aria-current': t.route === current ? 'page' : null,
      }, icon(t.icon, { size: 22 }), h('span', null, t.label))),
    ),
  );
}

/** Top bar: back link, centered title, optional right element. */
export function topbar({ back = 'home', backLabel = 'Back', title, titleTag = 'h1', right } = {}) {
  return h('header', { class: 'topbar' },
    back
      ? h('a', { class: 'icon-btn', href: `#/${back}`, 'aria-label': backLabel }, icon('back', { size: 22, stroke: 1.8 }))
      : h('span', { class: 'spacer' }),
    h(titleTag, { class: 'title' }, title || ''),
    right || h('span', { class: 'spacer' }),
  );
}

/** Small uppercase section heading. */
export function eyebrow(text, { tag = 'h2', id, gold = false } = {}) {
  return h(tag, { class: gold ? 'eyebrow gold' : 'eyebrow', id }, text);
}

let uid = 0;
export function nextId(prefix = 'id') {
  uid += 1;
  return `${prefix}-${uid}`;
}
