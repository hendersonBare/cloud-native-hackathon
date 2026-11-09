import { after, before, describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { FakeElement, install } from './fake-dom.mjs';

const fixture = JSON.parse(readFileSync(fileURLToPath(new URL('../swarm/demo-events.json', import.meta.url)), 'utf8'));

describe('swarm panel rendering', () => {
  let restore;
  let createSwarmPanel;
  let acceptPhase;
  before(async () => {
    restore = install();
    ({ createSwarmPanel } = await import('../swarm/panel.js'));
    ({ acceptPhase } = await import('../swarm/driver.js'));
  });
  after(() => restore());

  const el = () => new FakeElement('aside');
  const feed = (panel, events) => events.forEach(({ event }) => panel.dispatch(event));
  const text = (node) => node.textContent.replace(/\s+/g, ' ').trim();

  test('starts empty with a status and an aria-live timeline', () => {
    const root = el();
    createSwarmPanel(root);
    assert.equal(root.getAttribute('aria-labelledby'), 'swarm-title');
    const [timeline] = root.byClass('sw-timeline');
    assert.equal(timeline.getAttribute('aria-live'), 'polite');
    assert.equal(timeline.getAttribute('tabindex'), '0');
    assert.equal(timeline.children.length, 0);
    assert.match(text(root.byClass('sw-status')[0]), /Waiting for a connection/);
  });

  test('the full accept phase shows pods, rounds 1 to 3, the red pricing chip and completion', () => {
    const root = el();
    const panel = createSwarmPanel(root);
    feed(panel, acceptPhase(fixture));

    assert.match(text(root.byClass('sw-pair')[0]), /Ava.*Bo/);
    assert.equal(root.byClass('sw-lane').length, 2);
    assert.deepEqual(root.byClass('sw-lane').map((l) => l.dataset.org), ['acme', 'bluefin']);
    const pods = root.byClass('sw-pod');
    assert.equal(pods.length, 2);
    assert.ok(pods.every((p) => p.classList.contains('is-running')));
    assert.ok(pods.every((p) => text(p).includes('Running')));

    const rounds = root.byClass('sw-round').map((r) => r.textContent);
    assert.deepEqual(rounds, ['Round 1', 'Round 1', 'Round 2', 'Round 2', 'Round 3', 'Round 3']);

    const deny = root.byClass('is-deny');
    assert.equal(deny.length, 1);
    assert.match(text(deny[0]), /Denied/);
    assert.match(text(deny[0]), /pricing_needs_approval/);
    assert.match(text(deny[0]), /Pricing overview 2026/);
    // Never colour alone: the chip carries an icon as well as the words.
    assert.equal(deny[0].findAll((n) => n.tagName === 'SVG').length, 1);
    const allow = root.byClass('is-allow');
    assert.equal(allow.length, 3);
    assert.ok(allow.every((a) => /Allowed/.test(text(a))));

    assert.equal(root.byClass('sw-status')[0].getAttribute('data-status'), 'completed');
    assert.match(text(root.byClass('sw-timeline')[0]), /Encounter completed/);
  });

  test('entry times use America/Denver with the MST label', () => {
    const root = el();
    const panel = createSwarmPanel(root);
    panel.dispatch({ type: 'encounter_started', ts: '2026-11-09T22:30:00Z', encounter_id: 'e', data: {
      initiator_persona_id: 'acme.ava', responder_persona_id: 'bluefin.bo',
    } });
    const [time] = root.findAll((n) => n.tagName === 'TIME');
    assert.equal(time.textContent, '3:30:00 PM MST');
    assert.equal(time.getAttribute('datetime'), '2026-11-09T22:30:00.000Z');
  });

  test('new events append; existing timeline nodes are kept so the live region announces once', () => {
    const root = el();
    const panel = createSwarmPanel(root);
    const events = acceptPhase(fixture);
    feed(panel, events.slice(0, 4));
    const [timeline] = root.byClass('sw-timeline');
    const before = [...timeline.children];
    assert.equal(before.length, 1 + 0 + 0); // started only: pod_status updates lanes, not the timeline
    feed(panel, events.slice(4, 10));
    assert.ok(timeline.children.length > before.length);
    assert.equal(timeline.children[0], before[0]);
  });

  test('counterparty text is rendered as text, never as markup', () => {
    const root = el();
    const panel = createSwarmPanel(root);
    const payload = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    panel.dispatch({ type: 'exchange_message', ts: '2026-11-09T22:30:00Z', encounter_id: 'e', data: {
      round: 2, type: 'offers_asks', from_org: 'bluefin', to_org: 'acme', display: payload,
    } });
    panel.dispatch({ type: 'policy_decision', ts: '2026-11-09T22:30:01Z', encounter_id: 'e', data: {
      org_id: 'acme', action: 'answer', item_id: 'i', item_title: payload, decision: 'deny', rule_id: payload,
    } });
    const tags = root.findAll(() => true).map((n) => n.tagName);
    assert.ok(!tags.includes('IMG'));
    assert.ok(!tags.includes('SCRIPT'));
    assert.ok(text(root).includes(payload.slice(0, 40)));
  });

  test('declined, failed and stopped states are announced in the status', () => {
    const root = el();
    const panel = createSwarmPanel(root);
    panel.dispatch({ type: 'request_declined', ts: 't', data: {} });
    assert.match(text(root.byClass('sw-status')[0]), /declined/);
    panel.dispatch({ type: 'encounter_completed', ts: 't', data: { status: 'failed' } });
    assert.match(text(root.byClass('sw-status')[0]), /failed/);
  });

  test('unrecognised events do not redraw', () => {
    const panel = createSwarmPanel(el());
    assert.equal(panel.dispatch({ type: 'private_brief', data: {} }), false);
  });

  test('reset clears lanes and timeline', () => {
    const root = el();
    const panel = createSwarmPanel(root);
    feed(panel, acceptPhase(fixture));
    panel.reset();
    assert.equal(root.byClass('sw-lane').length, 0);
    assert.equal(root.byClass('sw-timeline')[0].children.length, 0);
    assert.equal(root.byClass('sw-status')[0].getAttribute('data-status'), 'idle');
  });
});

describe('swarm panel show/hide', () => {
  let restore;
  let initSwarm;
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  before(async () => {
    restore = install();
    globalThis.window = globalThis;
    const store = new Map();
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) },
    });
    ({ initSwarm } = await import('../swarm/index.js'));
  });
  after(() => {
    restore();
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow);
    else delete globalThis.window;
    if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage);
    else delete globalThis.localStorage;
  });

  function mount(mode = 'live') {
    const root = new FakeElement('aside');
    const toggle = new FakeElement('button');
    const stage = new FakeElement('main');
    const layouts = [];
    const opened = [];
    const swarm = initSwarm({
      root, toggle, stage, mode, onLayout: () => layouts.push(root.hidden),
      openStream: (query, onEvent) => { opened.push({ query, onEvent, closed: false }); return () => { opened.at(-1).closed = true; }; },
      relay: undefined,
    });
    return { root, toggle, stage, layouts, opened, swarm };
  }

  test('is shown by default and the toggle hides and shows it', () => {
    const { root, toggle, stage, layouts } = mount();
    assert.equal(root.hidden, false);
    assert.equal(stage.classList.contains('has-swarm'), true);
    assert.equal(toggle.getAttribute('aria-pressed'), 'true');
    assert.equal(toggle.textContent, 'Hide swarm panel');
    toggle.click();
    assert.equal(root.hidden, true);
    assert.equal(stage.classList.contains('has-swarm'), false);
    assert.equal(toggle.getAttribute('aria-pressed'), 'false');
    assert.equal(toggle.textContent, 'Show swarm panel');
    toggle.click();
    assert.equal(root.hidden, false);
    // The stage re-fits the phones every time the layout changes.
    assert.deepEqual(layouts, [false, true, false]);
  });

  test('live mode reads only the swarm stream, relays events, and keeps updating while hidden', () => {
    const { toggle, opened, swarm } = mount('live');
    assert.deepEqual(opened.map((o) => o.query), ['view=swarm']);
    toggle.click(); // hidden
    opened[0].onEvent({ type: 'encounter_started', encounter_id: 'e', ts: 't', data: {
      initiator_persona_id: 'acme.ava', responder_persona_id: 'bluefin.bo',
    } });
    assert.equal(swarm.panel.getState().status, 'running');
  });

  test('reset clears the panel and reopens the live stream', () => {
    const { opened, swarm } = mount('live');
    opened[0].onEvent({ type: 'encounter_started', encounter_id: 'e', ts: 't', data: {
      initiator_persona_id: 'acme.ava', responder_persona_id: 'bluefin.bo',
    } });
    swarm.reset();
    assert.equal(opened.length, 2);
    assert.equal(swarm.panel.getState().status, 'idle');
  });
});
