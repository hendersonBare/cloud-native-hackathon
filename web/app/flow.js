// App-lifetime listeners run before screen listeners and own encounter state.
import { h, avatar, nextId } from './ui.js';
import { person } from './data.js';
import { api } from './api.js';
import { showNotification } from './notify.js';
import { initLiveEvents } from './live-events.js';
import { swipeScript } from './demo-script.js';

// Without a gateway there is no server request id, so the phone makes one with this prefix.
const MOCK_REQUEST = 'req-mock-';

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

// Non-guessable id: randomUUID needs a secure context, getRandomValues doesn't.
function encounterSuffix() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function initFlow({ me, peer, store, mode, go, bus, overlay }) {
  flowOverlay = overlay;
  let lastStart = null;
  let disposed = false;
  let closeNotice = null;
  let noticeDismissed = false;
  const started = new Set();
  const cleanups = [];
  // Incoming connect request for this phone, or null. Written only here; person.js
  // and people.js render Accept/Decline from it and answer with a local 'ui:respond'.
  store.incoming = null;

  function hideNotice() {
    closeNotice?.();
    closeNotice = null;
  }

  function clearIncoming() {
    if (!store.incoming) return;
    const { request_id } = store.incoming;
    store.incoming = null;
    noticeDismissed = false;
    hideNotice();
    bus.emitLocal('request:cleared', { request_id });
  }

  function showIncomingNotice() {
    const req = store.incoming;
    const requester = req && person(req.from);
    if (!requester) return;
    hideNotice();
    closeNotice = showNotification(overlayRoot(), {
      title: req.initiated_by === 'agent'
        ? `${requester.name}'s agent wants to connect`
        : `${requester.name} wants your agents to talk`,
      body: CONTENT[me.id] || `${requester.role}`,
      cta: 'See what your agent found',
      avatarEl: avatar(requester.initials, requester.tone, 38, 14),
      onOpen: () => {
        closeNotice = null;
        go('person', { id: req.from, request: req.request_id, from: 'request' });
      },
      onDismiss: () => {
        closeNotice = null;
        noticeDismissed = true;
      },
    });
  }

  function respond(accept) {
    const req = store.incoming;
    if (!req) return;
    clearIncoming();
    if (!accept) {
      bus.emit('encounter:declined', { encounter_id: null, initiator: req.from, responder: me.id });
      return;
    }
    const enc = {
      encounter_id: `enc-${encounterSuffix()}`, initiator: req.from, responder: me.id,
      startedAt: Date.now() + 600, status: 'talking',
    };
    store.encounter = enc;
    bus.emit('encounter:start', enc);
    if (mode !== 'live') return;
    if (req.request_id.startsWith(MOCK_REQUEST)) {
      console.warn('Cannot accept a live connection without a request_id');
      return;
    }
    store.encounter.request_id = req.request_id;
    api.accept(req.request_id, { persona_id: me.id }).catch(() => {
      if (disposed) return;
      console.warn('Accept request failed');
      toast('Could not confirm the connection. Try again.', { tone: 'error' });
    });
  }

  cleanups.push(bus.on('ui:respond', ({ request_id, accept } = {}) => {
    if (!store.incoming || (request_id && request_id !== store.incoming.request_id)) return;
    respond(accept === true);
  }));

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
    if (!person(from)) {
      console.warn('Connect request has an unknown persona');
      return;
    }
    // The other phone's local broadcast can arrive before the server's request id:
    // enrich the pending request instead of replacing it.
    const current = store.incoming;
    if (current && current.from === from && current.to === to
      && (!request_id || current.request_id.startsWith(MOCK_REQUEST) || request_id === current.request_id)) {
      if (request_id) current.request_id = request_id;
      current.initiated_by = initiated_by;
      bus.emitLocal('request:incoming', current);
      if (closeNotice) showIncomingNotice();
      return;
    }
    clearIncoming();
    store.incoming = { request_id: request_id || `${MOCK_REQUEST}${encounterSuffix().slice(0, 12)}`, from, to, initiated_by };
    bus.emitLocal('request:incoming', store.incoming);
    showIncomingNotice();
  }));

  // A swipe on Home. With a gateway, it researches the person, decides, and for agent_handshake
  // creates the connect request itself, so this never calls api.connect. Without one, a right
  // swipe replays the same events from the demo script (deep dive, decision, agent's request),
  // or connects directly when the script doesn't cover that person.
  const scriptTimers = new Set();
  cleanups.push(() => { for (const t of scriptTimers) clearTimeout(t); scriptTimers.clear(); });
  function playSwipe(from, to) {
    const steps = swipeScript(from, to);
    if (!steps.length) {
      bus.emit('ui:connect', { from, to, initiated_by: 'human' });
      return;
    }
    for (const step of steps) {
      const timer = setTimeout(() => {
        scriptTimers.delete(timer);
        if (disposed) return;
        if (step.type === 'connect_request') bus.emit('ui:connect', { from, to, initiated_by: 'agent' });
        else bus.emitLocal(`gateway:${step.type}`, step.event);
      }, step.at_ms);
      scriptTimers.add(timer);
    }
  }
  cleanups.push(bus.on('ui:swipe', ({ from, to, direction } = {}) => {
    if (from !== me.id || (direction !== 'left' && direction !== 'right')) return;
    if (mode !== 'live') {
      if (direction === 'right') playSwipe(from, to);
      return;
    }
    api.swipe({
      persona_id: from, target_persona_id: to, direction, autonomy: true, malicious: !!store.config?.malicious,
    }).catch(() => {
      if (disposed) return;
      console.warn('Swipe request failed');
      toast('Your agent could not act on that swipe. Try again.', { tone: 'error' });
    });
  }));

  // The agent decided to start a handshake: wait for the target to accept (their phone got connect_request).
  cleanups.push(bus.on('gateway:agent_decision', (event) => {
    const data = event?.data;
    if (event?.persona_id !== me.id || data?.action !== 'agent_handshake' || !person(data.target_persona_id)) return;
    if (store.encounter?.status === 'talking') return;
    store.encounter = {
      encounter_id: null, initiator: me.id, responder: data.target_persona_id, startedAt: null,
      status: 'waiting', request_id: data.request_id,
    };
  }));
  // A pending request the person opened but didn't answer comes back when they
  // leave its brief (not after they dismissed the banner themselves).
  function onRoute() {
    const req = store.incoming;
    if (!req || closeNotice || noticeDismissed) return;
    const onBrief = /^#\/person\?/.test(location.hash) && new URLSearchParams(location.hash.split('?')[1]).get('id') === req.from;
    if (!onBrief) showIncomingNotice();
  }
  window.addEventListener('hashchange', onRoute);
  cleanups.push(() => window.removeEventListener('hashchange', onRoute));

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
    if (store.incoming?.from === enc.initiator) clearIncoming();
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
      if (store.incoming?.from === initiator) clearIncoming();
    }
  }));

  cleanups.push(bus.on('encounter:done', ({ encounter_id, stopped }) => {
    if (store.encounter && (encounter_id == null || store.encounter.encounter_id === encounter_id)) {
      if (stopped) store.encounter = null;
      else store.encounter.status = 'done';
    }
  }));

  // Briefs, deep dive and the agent's decision, from the gateway or from the demo script.
  cleanups.push(initLiveEvents({ me, store, bus, toast, go }));

  if (mode === 'live') {
    // The gateway sends exchange_message and policy_decision to the swarm stream only (SPEC 7.1),
    // which the stage relays as 'gateway:swarm'. They are also accepted here, deduplicated, in case
    // a gateway ever routes them to a phone stream.
    const seenExchange = new Set();
    const applyExchange = (event) => {
      const data = event.data || {};
      const encounter_id = event.encounter_id;
      const key = JSON.stringify([event.type, event.ts, encounter_id, data]);
      if (seenExchange.has(key)) return;
      seenExchange.add(key);
      if (event.type === 'exchange_message') {
        const parties = [store.encounter?.initiator, store.encounter?.responder];
        const sender = parties.map(person).find((p) => p?.org === data.from_org)
          || [me, peer].find((p) => p.org === data.from_org);
        bus.emitLocal('exchange:message', {
          ...data, encounter_id, from: sender?.id || data.from_org, text: data.display,
        });
      } else if (event.type === 'policy_decision') {
        bus.emitLocal('exchange:policy', { ...data, encounter_id, allow: data.decision === 'allow' });
      }
    };
    cleanups.push(bus.on('gateway:swarm', (event) => {
      if (event?.type === 'exchange_message' || event?.type === 'policy_decision') applyExchange(event);
    }));
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
        case 'exchange_message':
        case 'policy_decision':
          applyExchange(event);
          break;
        case 'encounter_completed':
          bus.emitLocal('encounter:done', { ...data, encounter_id });
          if (data.status === 'failed') toast('The agents could not finish the conversation.', { tone: 'error' });
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
    hideNotice();
    activeSheet?.();
    activeToast?.();
    started.clear();
    window.removeEventListener('pagehide', cleanup);
  }
  window.addEventListener('pagehide', cleanup, { once: true });
  return cleanup;
}
