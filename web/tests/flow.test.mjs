// Incoming connect requests: flow.js keeps ctx.store.incoming, shows a
// push-style notification, opens the requester's brief on tap, and answers
// 'ui:respond' from the brief. A tiny fake DOM and a fake bus stand in for the
// browser and the BroadcastChannel.
import { describe, it, before, after } from 'node:test';
import assert from 'node:assert/strict';

class FakeNode {
  constructor() { this.childNodes = []; this.parent = null; }
  append(...nodes) {
    for (const n of nodes) {
      const node = n instanceof FakeNode ? n : new FakeText(String(n));
      node.parent = this;
      this.childNodes.push(node);
    }
  }
  remove() {
    if (!this.parent) return;
    this.parent.childNodes = this.parent.childNodes.filter((c) => c !== this);
    this.parent = null;
  }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }
}
class FakeText extends FakeNode {
  constructor(data) { super(); this.nodeType = 3; this.data = data; }
  get textContent() { return this.data; }
}
class FakeElement extends FakeNode {
  constructor(tag) {
    super();
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.attrs = new Map();
    this.listeners = {};
    this.dataset = {};
    this.style = { setProperty: (k, v) => { this.style[k] = v; } };
  }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  fire(type, event = {}) { for (const fn of this.listeners[type] || []) fn(event); }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  find(cls) {
    for (const c of this.children) {
      if ((c.getAttribute('class') || '').split(' ').includes(cls)) return c;
      const hit = c.find(cls);
      if (hit) return hit;
    }
    return null;
  }
}

// web/tests/index.js runs every test file in one process, so these fakes are
// installed only while this suite runs and the previous globals are restored after.
const FAKES = {
  Node: FakeNode,
  document: {
    createElement: (tag) => new FakeElement(tag),
    createElementNS: (_ns, tag) => new FakeElement(tag),
    createTextNode: (data) => new FakeText(data),
    getElementById: () => null,
  },
  location: { hash: '' },
  window: { addEventListener() {}, removeEventListener() {} },
};
let saved = null;
let initFlow;
let person;

function installFakes() {
  saved = Object.fromEntries(Object.keys(FAKES).map((k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  for (const [k, v] of Object.entries(FAKES)) {
    Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true });
  }
}
function restoreGlobals() {
  for (const [k, desc] of Object.entries(saved || {})) {
    if (desc) Object.defineProperty(globalThis, k, desc);
    else delete globalThis[k];
  }
}

function makeBus() {
  const listeners = new Map();
  const sent = [];
  const dispatch = (type, data) => { for (const fn of [...(listeners.get(type) || [])]) fn(data); };
  return {
    sent,
    on(type, fn) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(fn);
      return () => listeners.get(type)?.delete(fn);
    },
    emitLocal(type, data) { sent.push({ type, data, scope: 'local' }); dispatch(type, data); },
    emit(type, data) { sent.push({ type, data, scope: 'broadcast' }); dispatch(type, data); },
  };
}

// Bo's phone, receiving from Ava (the demo flow).
function setup() {
  const bus = makeBus();
  const store = { config: { malicious: false } };
  const overlay = new FakeElement('div');
  const routes = [];
  const cleanup = initFlow({
    me: person('bluefin.bo'), peer: person('acme.ava'), store, mode: 'mock',
    go: (name, params) => routes.push([name, params]), bus, overlay,
  });
  const notice = () => overlay.find('notice');
  const sentOf = (type) => bus.sent.filter((m) => m.type === type);
  return { bus, store, overlay, routes, cleanup, notice, sentOf };
}

const connect = (bus, extra = {}) => bus.emitLocal('ui:connect', { from: 'acme.ava', to: 'bluefin.bo', ...extra });

describe('incoming connect requests', () => {
  before(async () => {
    installFakes();
    ({ initFlow } = await import('../app/flow.js'));
    ({ person } = await import('../app/data.js'));
  });
  after(restoreGlobals);

  it('a request to me is stored, announced and shown as a notification', (t) => {
    const s = setup();
    t.after(s.cleanup);
    connect(s.bus, { initiated_by: 'agent' });
    assert.equal(s.store.incoming.from, 'acme.ava');
    assert.equal(s.store.incoming.to, 'bluefin.bo');
    assert.match(s.store.incoming.request_id, /^req-mock-/);
    assert.deepEqual(s.sentOf('request:incoming').map((m) => m.data), [s.store.incoming]);
    assert.equal(s.notice().find('notice-title').textContent, "Ava's agent wants to connect");
  });

  it('tapping the notification opens the requester brief with the request id', (t) => {
    const s = setup();
    t.after(s.cleanup);
    connect(s.bus);
    const { request_id } = s.store.incoming;
    s.notice().find('notice-main').fire('click');
    assert.deepEqual(s.routes, [['person', { id: 'acme.ava', request: request_id, from: 'request' }]]);
    assert.equal(s.notice(), null);
    assert.ok(s.store.incoming, 'opening the brief does not answer the request');
  });

  it('dismissing hides the banner but keeps the request pending', (t) => {
    const s = setup();
    t.after(s.cleanup);
    connect(s.bus);
    s.notice().find('notice-dismiss').fire('click');
    assert.equal(s.notice(), null);
    assert.ok(s.store.incoming);
    assert.equal(s.sentOf('encounter:declined').length, 0);
  });

  it('accepting through ui:respond starts the encounter on both phones', (t) => {
    const s = setup();
    t.after(s.cleanup);
    connect(s.bus);
    const { request_id } = s.store.incoming;
    s.bus.emitLocal('ui:respond', { request_id, accept: true });
    assert.equal(s.store.incoming, null);
    assert.deepEqual(s.sentOf('request:cleared').map((m) => m.data), [{ request_id }]);
    const [start] = s.sentOf('encounter:start');
    assert.equal(start.scope, 'broadcast');
    assert.equal(start.data.initiator, 'acme.ava');
    assert.equal(start.data.responder, 'bluefin.bo');
    assert.equal(s.store.encounter.status, 'talking');
    assert.deepEqual(s.routes.at(-1), ['exchange', undefined]);
    assert.equal(s.notice(), null);
  });

  it('declining through ui:respond tells the other phone', (t) => {
    const s = setup();
    t.after(s.cleanup);
    connect(s.bus);
    s.bus.emitLocal('ui:respond', { request_id: s.store.incoming.request_id, accept: false });
    const [declined] = s.sentOf('encounter:declined');
    assert.equal(declined.scope, 'broadcast');
    assert.deepEqual(declined.data, { encounter_id: null, initiator: 'acme.ava', responder: 'bluefin.bo' });
    assert.equal(s.store.incoming, null);
    assert.equal(s.sentOf('encounter:start').length, 0);
  });

  it('a response for another request id is ignored', (t) => {
    const s = setup();
    t.after(s.cleanup);
    connect(s.bus);
    s.bus.emitLocal('ui:respond', { request_id: 'req-stale', accept: true });
    assert.ok(s.store.incoming);
    assert.equal(s.sentOf('encounter:start').length, 0);
  });

  it("the server's request id enriches the pending request instead of adding one", (t) => {
    const s = setup();
    t.after(s.cleanup);
    connect(s.bus);
    connect(s.bus, { request_id: 'req-123', initiated_by: 'agent' });
    assert.equal(s.store.incoming.request_id, 'req-123');
    assert.equal(s.sentOf('request:cleared').length, 0);
    assert.equal(s.overlay.children.filter((c) => c.getAttribute('class') === 'notice').length, 1);
  });

  it('sending a request myself waits for the answer and shows no notification', (t) => {
    const s = setup();
    t.after(s.cleanup);
    s.bus.emitLocal('ui:connect', { from: 'bluefin.bo', to: 'acme.ava' });
    assert.equal(s.store.incoming, null);
    assert.equal(s.store.encounter.status, 'waiting');
    assert.equal(s.notice(), null);
  });

  it('notification text is plain text, never markup', (t) => {
    const s = setup();
    t.after(s.cleanup);
    connect(s.bus);
    const title = s.notice().find('notice-title');
    assert.equal(title.children.length, 0);
    assert.equal(title.childNodes[0].nodeType, 3);
  });
});
