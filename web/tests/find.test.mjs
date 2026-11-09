// The Find screen's GPS, sharing and polling logic. A tiny fake DOM, a drivable fake
// navigator.geolocation, fake timers and a stub venue client (injected as ctx.store.venueClient)
// stand in for the browser and the venue API.
import { describe, it, before, after, beforeEach, afterEach, mock } from 'node:test';
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
    this.tagName = tag;
    this.attrs = new Map();
    this.listeners = {};
    this.dataset = {};
    this.hidden = false;
    this.disabled = false;
    this.style = { setProperty: (k, v) => { this.style[k] = v; } };
  }
  set textContent(text) { this.childNodes = []; this.append(String(text)); }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }
  replaceChildren(...nodes) { this.childNodes = []; this.append(...nodes); }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  fire(type) { for (const fn of this.listeners[type] || []) fn({}); }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  findAll(cls, out = []) {
    for (const c of this.children) {
      if ((c.getAttribute('class') || '').split(' ').includes(cls)) out.push(c);
      c.findAll(cls, out);
    }
    return out;
  }
  find(cls) { return this.findAll(cls)[0] || null; }
}

// web/tests/index.js runs every test file in one process, so the fakes are installed only while
// this suite runs and the previous globals are restored after.
const FAKES = {
  Node: FakeNode,
  document: {
    createElement: (tag) => new FakeElement(tag),
    createElementNS: (_ns, tag) => new FakeElement(tag),
    createTextNode: (data) => new FakeText(data),
  },
};
const GLOBALS = [...Object.keys(FAKES), 'navigator'];
let saved = null;
let render;
let person;

function installFakes() {
  saved = Object.fromEntries(GLOBALS.map((k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  for (const [k, v] of Object.entries(FAKES)) {
    Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true });
  }
}
function setNavigator(value) {
  Object.defineProperty(globalThis, 'navigator', { value, configurable: true, writable: true });
}
function restoreGlobals() {
  for (const [k, desc] of Object.entries(saved || {})) {
    if (desc) Object.defineProperty(globalThis, k, desc);
    else delete globalThis[k];
  }
}

// ---------------------------------------------------------------- fakes

const VENUE = {
  width_m: 100, height_m: 60, corridor_y: 30,
  rooms: [
    { id: 'hall', name: 'Main hall', x: 0, y: 35, w: 50, h: 25, door: [25, 35] },
    { id: 'concourse', name: 'Concourse', x: 0, y: 25, w: 100, h: 10, corridor: true },
    { id: 'lobby', name: 'Lobby', x: 60, y: 0, w: 40, h: 25, door: [75, 25] },
  ],
};
const FROM = { room_id: 'lobby', x: 70, y: 18, source: 'checkin', accuracy_m: null };
const dirTo = (distance, source = 'gps') => ({
  from: FROM,
  to: { room_id: 'hall', x: 20, y: 50, source, updated_at: '2026-01-01T00:00:00Z' },
  route: [[70, 18], [20, 50]],
  legs: [{ kind: 'same_room', room_id: 'lobby' }, { kind: 'arrive', meters: 5, compass: 'east' }],
  distance_m: distance,
  peer_status: 'sharing',
});
const DIR = dirTo(40);
const DIR_HIDDEN = { from: FROM, to: null, route: [], legs: [], distance_m: null, peer_status: 'not_sharing' };

function deferred() {
  const d = {};
  d.promise = new Promise((resolve, reject) => { d.resolve = resolve; d.reject = reject; });
  return d;
}
const venueError = (status) => Object.assign(new Error(`venue request failed with status ${status}`), { name: 'VenueError', status });

/** A venue client whose methods are replaceable through `impl`; every call is recorded. */
function makeApi(sharing) {
  const calls = { directions: 0, updateLocation: [], setSharing: [] };
  const impl = {
    view: async () => ({ venue: VENUE, sharing }),
    directions: async () => DIR,
    updateLocation: async () => ({}),
    setSharing: async (body) => ({ persona_id: body.persona_id, enabled: body.enabled }),
  };
  const api = {
    view: (...a) => impl.view(...a),
    directions: (...a) => { calls.directions += 1; return impl.directions(...a); },
    updateLocation: (body) => { calls.updateLocation.push(body); return impl.updateLocation(body); },
    setSharing: (body) => { calls.setSharing.push(body); return impl.setSharing(body); },
  };
  return { api, calls, impl };
}

/** A navigator.geolocation you can drive: emit fixes and errors, see which watches were cleared. */
function makeGeo() {
  const geo = {
    watchers: new Map(), cleared: [], nextId: 1,
    watchPosition(ok, err) { const id = geo.nextId++; geo.watchers.set(id, { ok, err }); return id; },
    clearWatch(id) { geo.cleared.push(id); geo.watchers.delete(id); },
    emit(latitude, longitude, accuracy) { for (const w of geo.watchers.values()) w.ok({ coords: { latitude, longitude, accuracy } }); },
    fail(code) { for (const w of geo.watchers.values()) w.err({ code }); },
  };
  return geo;
}

function makeBus() {
  const listeners = new Map();
  return {
    count: (type) => listeners.get(type)?.size || 0,
    on(type, fn) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(fn);
      return () => listeners.get(type).delete(fn);
    },
    emit(type, data) { for (const fn of [...(listeners.get(type) || [])]) fn(data); },
  };
}

const flush = async () => { for (let i = 0; i < 4; i += 1) await new Promise((r) => setImmediate(r)); };
const POLL_MS = 5000;
const SEND_MS = 10000;

/** Render the Find screen for Ava looking for Bo. `sharing` is what the server says at load. */
async function setup({ sharing = false, geo = makeGeo() } = {}) {
  setNavigator(geo ? { geolocation: geo } : {});
  const bus = makeBus();
  const { api, calls, impl } = makeApi(sharing);
  const cleanups = [];
  const ctx = {
    me: person('acme.ava'), person, bus, mode: 'mock', store: { venueClient: api },
    route: { name: 'find', params: { with: 'bluefin.bo' } },
    onCleanup: (fn) => cleanups.push(fn),
  };
  const root = render(ctx);
  await flush();
  const s = {
    root, geo, bus, calls, impl,
    note: () => root.find('find-share-note').textContent,
    status: () => root.find('find-status').textContent,
    fresh: () => root.find('find-fresh').textContent,
    steps: () => root.findAll('find-step').map((e) => e.textContent),
    toggle: root.find('find-share'),
    main: root.find('find-main'),
    leave: () => { for (const fn of cleanups.splice(0)) fn(); },
    tick: async (ms) => { mock.timers.tick(ms); await flush(); },
    fix: async (accuracy = 12, lat = 40, lng = -105) => { geo.emit(lat, lng, accuracy); await flush(); },
    click: async () => { s.toggle.fire('click'); await flush(); },
  };
  return s;
}

describe('Find screen', () => {
  before(async () => {
    installFakes();
    ({ render } = await import('../app/screens/find.js'));
    ({ person } = await import('../app/data.js'));
  });
  after(restoreGlobals);
  beforeEach(() => { mock.timers.enable({ apis: ['setInterval', 'Date'], now: 1_700_000_000_000 }); });
  afterEach(() => { mock.timers.reset(); setNavigator(undefined); });

  describe('GPS states', () => {
    it('is off until sharing is on, and the route comes from the check-in spot', async (t) => {
      const s = await setup();
      t.after(s.leave);
      assert.match(s.note(), /^Off · nobody can find you/);
      assert.equal(s.toggle.getAttribute('aria-checked'), 'false');
      assert.equal(s.geo.watchers.size, 0);
      assert.equal(s.main.getAttribute('aria-busy'), 'false');
    });

    it('waiting: sharing is on but no fix has arrived yet', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      assert.equal(s.note(), 'On · finding you…');
      assert.equal(s.geo.watchers.size, 1);
      assert.equal(s.toggle.getAttribute('aria-checked'), 'true');
    });

    it('weak: a fix over the accuracy limit is not sent', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      await s.fix(101);
      assert.match(s.note(), /GPS signal is too weak/);
      assert.equal(s.calls.updateLocation.length, 0);
      await s.fix(100);
      assert.equal(s.calls.updateLocation.length, 1, 'exactly the limit is fine');
    });

    it('denied: error code 1 means the permission is blocked', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      s.geo.fail(1);
      await flush();
      assert.match(s.note(), /location permission is blocked/);
    });

    it('unavailable: any other GPS error', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      s.geo.fail(2);
      await flush();
      assert.match(s.note(), /can't get a GPS fix/);
    });

    it('unavailable: a device without geolocation', async (t) => {
      const s = await setup({ sharing: true, geo: null });
      t.after(s.leave);
      assert.match(s.note(), /can't get a GPS fix/);
    });

    it('outside: the venue rejects the fix with 422', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      s.impl.updateLocation = async () => { throw venueError(422); };
      await s.fix();
      assert.match(s.note(), /not at the venue right now/);
    });

    it('on: an accepted fix shows the accuracy', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      await s.fix(12.4);
      assert.equal(s.note(), "On · your phone's GPS, within 12 m");
      assert.deepEqual(s.calls.updateLocation, [{ persona_id: 'acme.ava', lat: 40, lng: -105, accuracy_m: 12.4 }]);
    });

    it('on: a fix without an accuracy is sent with null and shows no radius', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      await s.fix(null);
      assert.equal(s.calls.updateLocation[0].accuracy_m, null);
      assert.equal(s.note(), "On · your phone's GPS");
    });

    it('another server error keeps the current state', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      s.impl.updateLocation = async () => { throw venueError(409); };
      await s.fix();
      assert.equal(s.note(), 'On · finding you…');
    });
  });

  describe('sending fixes', () => {
    it('sends the first fix at once and then at most every 10 seconds', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      await s.fix(10, 40, -105);
      assert.equal(s.calls.updateLocation.length, 1);
      await s.fix(10, 41, -105);
      await s.fix(10, 42, -105);
      assert.equal(s.calls.updateLocation.length, 1, 'fixes inside the window are held back');
      await s.tick(SEND_MS - POLL_MS);
      assert.equal(s.calls.updateLocation.length, 1, 'the 5 s poll is still inside the window');
      await s.tick(POLL_MS);
      assert.equal(s.calls.updateLocation.length, 2);
      assert.equal(s.calls.updateLocation[1].lat, 42, 'the latest fix goes out, not the first held one');
    });

    it('does not start a second send while one is in flight', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      const pending = deferred();
      s.impl.updateLocation = () => pending.promise;
      await s.fix();
      await s.tick(SEND_MS);
      assert.equal(s.calls.updateLocation.length, 1);
      pending.resolve({});
      await flush();
      assert.equal(s.note(), "On · your phone's GPS, within 12 m");
    });

    it('redraws the directions after a send', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      const before = s.calls.directions;
      await s.fix();
      assert.equal(s.calls.directions, before + 1);
    });
  });

  describe('Share my location switch', () => {
    it('turning it on starts the GPS watch', async (t) => {
      const s = await setup();
      t.after(s.leave);
      await s.click();
      assert.deepEqual(s.calls.setSharing, [{ persona_id: 'acme.ava', enabled: true }]);
      assert.equal(s.toggle.getAttribute('aria-checked'), 'true');
      assert.equal(s.note(), 'On · finding you…');
      assert.equal(s.geo.watchers.size, 1);
      assert.equal(s.toggle.disabled, false);
    });

    it('turning it off stops the watch and forgets the fix', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      await s.fix();
      await s.click();
      assert.deepEqual(s.calls.setSharing, [{ persona_id: 'acme.ava', enabled: false }]);
      assert.equal(s.toggle.getAttribute('aria-checked'), 'false');
      assert.match(s.note(), /^Off · nobody can find you/);
      assert.equal(s.geo.watchers.size, 0);
      assert.deepEqual(s.geo.cleared, [1]);
    });

    it('a fix that arrives after turning it off is ignored', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      const { ok } = s.geo.watchers.get(1);
      await s.click();
      ok({ coords: { latitude: 1, longitude: 2, accuracy: 5 } });
      await flush();
      assert.equal(s.calls.updateLocation.length, 0);
      assert.match(s.note(), /^Off/);
    });

    it('a failed turn-on keeps it off', async (t) => {
      const s = await setup();
      t.after(s.leave);
      s.impl.setSharing = async () => { throw venueError(500); };
      await s.click();
      assert.equal(s.toggle.getAttribute('aria-checked'), 'false');
      assert.match(s.note(), /^Off/);
      assert.equal(s.geo.watchers.size, 0);
      assert.equal(s.toggle.disabled, false, 'the switch can be tried again');
    });

    it('a failed turn-off keeps it on and the watch running', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      await s.fix();
      s.impl.setSharing = async () => { throw venueError(500); };
      await s.click();
      assert.equal(s.toggle.getAttribute('aria-checked'), 'true');
      assert.equal(s.note(), "On · your phone's GPS, within 12 m");
      assert.equal(s.geo.watchers.size, 1);
      assert.equal(s.geo.cleared.length, 0);
    });
  });

  describe('a send in flight when sharing is turned off', () => {
    it('does not flip the note back to On when it succeeds', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      const pending = deferred();
      s.impl.updateLocation = () => pending.promise;
      await s.fix();
      await s.click();
      assert.match(s.note(), /^Off/);
      const before = s.calls.directions;
      pending.resolve({});
      await flush();
      assert.match(s.note(), /^Off · nobody can find you/);
      assert.equal(s.calls.directions, before, 'no redraw for a stale result');
    });

    it('does not show outside when it fails with 422', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      const pending = deferred();
      s.impl.updateLocation = () => pending.promise;
      await s.fix();
      await s.click();
      pending.reject(venueError(422));
      await flush();
      assert.match(s.note(), /^Off/);
    });

    it('does not apply to a later sharing session either', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      const first = deferred();
      s.impl.updateLocation = () => first.promise;
      await s.fix();
      await s.click(); // off
      await s.click(); // on again: waiting for a fresh fix
      assert.equal(s.note(), 'On · finding you…');
      first.resolve({});
      await flush();
      assert.equal(s.note(), 'On · finding you…', 'the old send says nothing about the new session');
    });
  });

  describe('directions refresh', () => {
    it('ignores a slow earlier answer that lands after a newer one', async (t) => {
      const s = await setup();
      t.after(s.leave);
      const first = deferred();
      const second = deferred();
      const queue = [first, second];
      s.impl.directions = () => queue.shift().promise;
      s.bus.emit('venue:changed');
      s.bus.emit('venue:changed');
      second.resolve(dirTo(10));
      await flush();
      assert.equal(s.status(), 'Main hall · 10\u00a0m away');
      first.resolve(dirTo(99));
      await flush();
      assert.equal(s.status(), 'Main hall · 10\u00a0m away', 'the stale answer is dropped');
    });

    it('ignores a stale failure after a newer success', async (t) => {
      const s = await setup();
      t.after(s.leave);
      const first = deferred();
      const second = deferred();
      const queue = [first, second];
      s.impl.directions = () => queue.shift().promise;
      s.bus.emit('venue:changed');
      s.bus.emit('venue:changed');
      second.resolve(dirTo(10));
      first.reject(venueError(500));
      await flush();
      assert.equal(s.status(), 'Main hall · 10\u00a0m away');
      assert.equal(s.root.find('find-error-slot').children.length, 0);
    });

    it('shows an error with a retry when the directions do not load', async (t) => {
      const s = await setup();
      t.after(s.leave);
      s.impl.directions = async () => { throw venueError(500); };
      s.bus.emit('venue:changed');
      await flush();
      const slot = s.root.find('find-error-slot');
      assert.equal(slot.find('empty-title').textContent, 'Directions did not load');
      s.impl.directions = async () => DIR;
      slot.find('find-retry').fire('click');
      await flush();
      assert.equal(slot.children.length, 0);
    });

    it('polls every 5 seconds', async (t) => {
      const s = await setup();
      t.after(s.leave);
      const before = s.calls.directions;
      await s.tick(POLL_MS * 2);
      assert.equal(s.calls.directions, before + 2);
    });
  });

  describe('leaving the screen', () => {
    it('stops the watch, the poll and the bus listener', async (t) => {
      const s = await setup({ sharing: true });
      await s.fix();
      assert.equal(s.bus.count('venue:changed'), 1);
      const before = s.calls.directions;
      s.leave();
      assert.deepEqual(s.geo.cleared, [1]);
      assert.equal(s.bus.count('venue:changed'), 0);
      s.bus.emit('venue:changed');
      await s.tick(POLL_MS * 3);
      assert.equal(s.calls.directions, before, 'no refresh after leaving');
      assert.equal(s.calls.updateLocation.length, 1, 'no send after leaving');
    });

    it('a send that lands after leaving changes nothing', async (t) => {
      const s = await setup({ sharing: true });
      t.after(s.leave);
      const pending = deferred();
      s.impl.updateLocation = () => pending.promise;
      await s.fix();
      s.leave();
      const before = s.calls.directions;
      pending.resolve({});
      await flush();
      assert.equal(s.note(), 'On · finding you…');
      assert.equal(s.calls.directions, before);
    });
  });

  describe('the other person', () => {
    it('shows their position and the steps while they share', async (t) => {
      const s = await setup();
      t.after(s.leave);
      assert.equal(s.status(), 'Main hall · 40\u00a0m away');
      assert.match(s.fresh(), /^Live GPS · updated /);
      assert.equal(s.steps()[0], "You're both in Lobby");
      assert.equal(s.root.findAll('peer-dot').length, 1);
      assert.ok(s.root.find('find-map').find('route'));
    });

    it('shows a check-in spot as not live', async (t) => {
      const s = await setup();
      t.after(s.leave);
      s.impl.directions = async () => dirTo(40, 'checkin');
      s.bus.emit('venue:changed');
      await flush();
      assert.equal(s.fresh(), 'Check-in spot · not live');
    });

    it('shows no position when they are not sharing', async (t) => {
      const s = await setup();
      t.after(s.leave);
      s.impl.directions = async () => DIR_HIDDEN;
      s.bus.emit('venue:changed');
      await flush();
      assert.equal(s.status(), "Isn't sharing a location right now");
      assert.equal(s.fresh(), '');
      assert.equal(s.root.findAll('peer-dot').length, 0);
      assert.equal(s.root.findAll('peer-initial').length, 0);
      assert.match(s.root.find('find-map').find('room').parent.getAttribute('aria-label'), /Bo is not sharing a location/);
      assert.deepEqual(s.steps(), ['When Bo turns on location sharing, the route shows here.']);
    });

    it('shows no position even if a stray position slips into the answer', async (t) => {
      const s = await setup();
      t.after(s.leave);
      s.impl.directions = async () => ({ ...DIR, peer_status: 'not_sharing' });
      s.bus.emit('venue:changed');
      await flush();
      assert.equal(s.status(), "Isn't sharing a location right now");
      assert.deepEqual(s.steps(), ['When Bo turns on location sharing, the route shows here.']);
    });
  });
});
