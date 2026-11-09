// App-lifetime listeners run before screen listeners and own encounter state.
import { h, avatar, icon, nextId } from './ui.js';
import { person } from './data.js';
import { api } from './api.js';

const CONTENT = {
  'bluefin.bo': 'Acme does zero-code eBPF tracing — no changes to clinical apps.',
  'acme.ava': 'Bluefin is looking for tracing without code changes.',
};

let flowOverlay = null;
let activeSheet = null;
let activeToast = null;

function overlayRoot() {
  return flowOverlay || document.getElementById('overlay');
}

export function toast(text, { tone = 'info' } = {}) {
  activeToast?.();
  const el = h('div', {
    class: 'toast flow-toast', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true', dataset: { tone },
  }, text);
  overlayRoot().append(el);
  const timer = setTimeout(close, 3000);
  function close() {
    clearTimeout(timer);
    el.remove();
    if (activeToast === close) activeToast = null;
  }
  activeToast = close;
  return close;
}

/** A single modal sheet. onClose also runs for Escape and backdrop dismissal. */
export function openSheet(contentEl, { label = 'Dialog', onClose } = {}) {
  activeSheet?.();
  const previousFocus = document.activeElement;
  const labelId = nextId('sheet-label');
  const sheet = h('div', {
    class: 'sheet flow-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': labelId, tabindex: '-1',
  },
  h('div', { class: 'grabber', 'aria-hidden': 'true' }),
  h('span', { id: labelId, class: 'visually-hidden' }, label),
  contentEl);
  const scrim = h('div', { class: 'scrim flow-scrim' }, sheet);
  const app = document.getElementById('app');
  const wasInert = app?.inert;
  let closed = false;

  function focusables() {
    return [...sheet.querySelectorAll(
      'a[href], button, input, select, textarea, [tabindex], [contenteditable="true"]',
    )].filter((el) => el.tabIndex >= 0 && !el.matches(':disabled') && !el.closest('[hidden], [inert]')
      && el.getClientRects().length > 0);
  }
  function focusInside() {
    (focusables()[0] || sheet).focus({ preventScroll: true });
  }
  function keepFocus(event) {
    if (!sheet.contains(event.target)) focusInside();
  }
  function keydown(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === 'Tab') {
      const targets = focusables();
      const first = targets[0];
      const last = targets[targets.length - 1];
      const focused = document.activeElement;
      if (!first) {
        event.preventDefault();
        sheet.focus();
      } else if (!targets.includes(focused) || (event.shiftKey ? focused === first : focused === last)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    }
  }
  function backdrop(event) {
    if (event.target === scrim) close();
  }
  function close() {
    if (closed) return;
    closed = true;
    document.removeEventListener('keydown', keydown, true);
    document.removeEventListener('focusin', keepFocus, true);
    scrim.removeEventListener('click', backdrop);
    scrim.remove();
    if (app) app.inert = wasInert;
    if (activeSheet === close) activeSheet = null;
    if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    onClose?.();
  }

  overlayRoot().append(scrim);
  if (app) app.inert = true;
  document.addEventListener('keydown', keydown, true);
  document.addEventListener('focusin', keepFocus, true);
  scrim.addEventListener('click', backdrop);
  activeSheet = close;
  focusInside();
  return close;
}

export function initFlow({ me, peer, store, mode, go, bus, overlay }) {
  flowOverlay = overlay;
  let pending = null;
  let lastStart = null;
  let disposed = false;
  const started = new Set();
  const cleanups = [];

  function dismissPending() {
    if (!pending) return;
    const request = pending;
    pending = null;
    request.settled = true;
    request.close();
  }

  cleanups.push(bus.on('ui:connect', ({ from, to, initiated_by = 'human', request_id }) => {
    if (from === me.id) {
      const encounter = {
        encounter_id: null, initiator: from, responder: to, startedAt: null, status: 'waiting',
      };
      store.encounter = encounter;
      if (mode === 'live') {
        api.connect({
          from_persona_id: from, to_persona_id: to, initiated_by, malicious: !!store.config?.malicious,
        }).then((result) => {
          if (disposed) return;
          if (store.encounter?.initiator === from && store.encounter?.responder === to) {
            store.encounter.request_id = result.request_id;
          }
        }).catch(() => {
          if (disposed) return;
          console.warn('Connect request failed');
          if (store.encounter === encounter) store.encounter = null;
          toast('Connection request failed. Try again.', { tone: 'error' });
        });
      }
    }
    if (to !== me.id) return;
    const requester = person(from);
    if (!requester) {
      console.warn('Connect request has an unknown persona');
      return;
    }
    const title = initiated_by === 'agent'
      ? `${requester.name}'s agent wants to connect`
      : `${requester.name} wants your agents to talk`;

    // A local broadcast can arrive before the server's request id. Enrich the
    // existing sheet so its Accept button uses the authoritative request.
    if (pending?.from === from && pending.to === to && (!request_id || !pending.request_id
      || request_id === pending.request_id)) {
      if (request_id) pending.request_id = request_id;
      pending.title.textContent = title;
      pending.label.textContent = title;
      return;
    }
    dismissPending();
    const request = { from, to, request_id, settled: false };
    pending = request;

    function decline() {
      if (request.settled) return;
      request.settled = true;
      request.close();
      if (pending === request) pending = null;
      bus.emit('encounter:declined', { encounter_id: null, initiator: from, responder: me.id });
    }
    function accept() {
      if (request.settled) return;
      request.settled = true;
      request.close();
      if (pending === request) pending = null;
      const random = globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2);
      const enc = {
        encounter_id: `enc-${random}`, initiator: from, responder: me.id,
        startedAt: Date.now() + 600, status: 'talking',
      };
      store.encounter = enc;
      bus.emit('encounter:start', enc);
      if (mode === 'live') {
        if (request.request_id) {
          store.encounter.request_id = request.request_id;
          api.accept(request.request_id, { persona_id: me.id }).catch(() => {
            if (disposed) return;
            console.warn('Accept request failed');
            toast('Could not confirm the connection. Try again.', { tone: 'error' });
          });
        } else {
          console.warn('Cannot accept a live connection without a request_id');
        }
      }
    }

    request.title = h('h2', { class: 'serif flow-connect-title' }, title);
    const content = h('div', { class: 'flow-connect' },
      h('div', { class: 'avatar-pair flow-connect-avatars', 'aria-hidden': 'true' },
        avatar(requester.initials, requester.tone, 52, 18), avatar(me.initials, me.tone, 52, 18)),
      request.title,
      h('p', { class: 'flow-connect-why' }, CONTENT[me.id]),
      h('div', { class: 'flow-connect-sharing' },
        h('p', { class: 'eyebrow' }, 'Their agent will share'),
        h('ul', { class: 'flow-connect-chips', 'aria-label': 'What their agent will share' },
          ['Role', 'Case study', 'Free/busy'].map((text) => h('li', { class: 'pill' }, text)))),
      h('p', { class: 'flow-connect-lock' }, icon('lock', { size: 16 }), 'Your private memory is never shared'),
      h('div', { class: 'action-row flow-connect-actions' },
        h('button', { type: 'button', class: 'btn', onClick: decline }, 'Decline'),
        h('button', { type: 'button', class: 'btn btn-primary', onClick: accept }, 'Accept')),
    );
    request.close = openSheet(content, { label: title, onClose: decline });
    request.label = content.parentElement.querySelector('.visually-hidden');
  }));

  cleanups.push(bus.on('encounter:start', (enc) => {
    if (enc.initiator !== me.id && enc.responder !== me.id) return;
    const key = enc.encounter_id || JSON.stringify([enc.initiator, enc.responder, enc.startedAt]);
    if (started.has(key)) return;
    // Live SSE replaces the optimistic demo id without navigating or announcing twice.
    const continuing = mode === 'live' && store.encounter?.status === 'talking'
      && lastStart?.initiator === enc.initiator && lastStart?.responder === enc.responder;
    store.encounter = { ...enc, status: 'talking' };
    started.add(key);
    lastStart = enc;
    dismissPending();
    if (continuing) return;
    go('exchange');
    if (enc.initiator === me.id) {
      const responder = person(enc.responder) || peer;
      toast(`${responder.name} accepted · your agents are talking`);
    }
  }));

  cleanups.push(bus.on('encounter:declined', ({ initiator, responder }) => {
    if (initiator === me.id) {
      if (store.encounter?.initiator === initiator && store.encounter?.responder === responder) {
        store.encounter.status = 'declined';
      }
      toast(`${(person(responder) || peer).name} declined`);
    }
    if (responder === me.id) {
      store.encounter = null;
      dismissPending();
    }
  }));

  cleanups.push(bus.on('encounter:done', ({ encounter_id, stopped }) => {
    if (store.encounter && (encounter_id == null || store.encounter.encounter_id === encounter_id)) {
      if (stopped) store.encounter = null;
      else store.encounter.status = 'done';
    }
  }));

  if (mode === 'live') {
    cleanups.push(api.openStream(`persona_id=${encodeURIComponent(me.id)}`, (event) => {
      const data = event.data;
      const encounter_id = event.encounter_id;
      switch (event.type) {
        case 'connect_request':
          bus.emitLocal('ui:connect', {
            from: data.from_persona_id, to: me.id, initiated_by: data.initiated_by, request_id: data.request_id,
          });
          break;
        case 'encounter_started':
          bus.emitLocal('encounter:start', {
            encounter_id, initiator: data.initiator_persona_id, responder: data.responder_persona_id,
            startedAt: Number.isNaN(Date.parse(event.ts)) ? Date.now() : Date.parse(event.ts),
          });
          break;
        case 'exchange_message': {
          const parties = [store.encounter?.initiator, store.encounter?.responder];
          const sender = parties.map(person).find((p) => p?.org === data.from_org)
            || [me, peer].find((p) => p.org === data.from_org);
          bus.emitLocal('exchange:message', {
            ...data, encounter_id, from: sender?.id || data.from_org, text: data.display,
          });
          break;
        }
        case 'policy_decision':
          bus.emitLocal('exchange:policy', { ...data, encounter_id, allow: data.decision === 'allow' });
          break;
        case 'encounter_completed':
          bus.emitLocal('encounter:done', { ...data, encounter_id });
          break;
      }
      // Keep the envelope (including trace/persona ids) intact and local to this phone.
      bus.emitLocal(`gateway:${event.type}`, event);
    }));
  }

  function cleanup() {
    if (disposed) return;
    disposed = true;
    for (const close of cleanups) close();
    dismissPending();
    activeSheet?.();
    activeToast?.();
    started.clear();
    window.removeEventListener('pagehide', cleanup);
  }
  window.addEventListener('pagehide', cleanup, { once: true });
  return cleanup;
}
