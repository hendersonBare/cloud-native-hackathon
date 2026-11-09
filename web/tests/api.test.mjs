import test from 'node:test';
import assert from 'node:assert/strict';
import * as api from '../app/api.js';

function stubFetch(t, response = new Response('{"ok":true}')) {
  return t.mock.method(globalThis, 'fetch', async () => response);
}

test('getPersonas sends a same-origin GET and parses the JSON response', async (t) => {
  const fetch = stubFetch(t, new Response('{"personas":[]}'));
  assert.deepEqual(await api.getPersonas(), { personas: [] });
  assert.equal(fetch.mock.callCount(), 1);
  assert.deepEqual(fetch.mock.calls[0].arguments, ['/api/personas', {
    method: 'GET', credentials: 'same-origin',
    headers: { Accept: 'application/json' }, body: undefined,
  }]);
});

test('getProfile encodes the persona query', async (t) => {
  const fetch = stubFetch(t);
  await api.getProfile('acme.ava +/ñ?');
  const [url, options] = fetch.mock.calls[0].arguments;
  assert.equal(url, '/api/profile?persona_id=acme.ava+%2B%2F%C3%B1%3F');
  assert.equal(options.method, 'GET');
  assert.equal(options.credentials, 'same-origin');
  assert.equal(options.body, undefined);
});

test('talks encodes both the persona and search query', async (t) => {
  const fetch = stubFetch(t);
  await api.talks('acme.ava +', 'eBPF & traces/ñ?');
  const [url, options] = fetch.mock.calls[0].arguments;
  assert.equal(url, '/api/talks?persona_id=acme.ava+%2B&q=eBPF+%26+traces%2F%C3%B1%3F');
  assert.equal(options.method, 'GET');
  assert.equal(options.credentials, 'same-origin');
  assert.equal(options.body, undefined);
});

test('talks defaults to an empty search query', async (t) => {
  const fetch = stubFetch(t);
  await api.talks('bluefin.bo');
  assert.equal(fetch.mock.calls[0].arguments[0], '/api/talks?persona_id=bluefin.bo&q=');
});

const jsonRequests = [
  ['connect', '/api/connect', { from: 'acme.ava', to: 'bluefin.bo' }],
  ['ask', '/api/ask', { persona_id: 'acme.ava', question: 'Synthetic question' }],
  ['research', '/api/research', { persona_id: 'acme.ava', interests: ['tracing'] }],
  ['swipe', '/api/swipe', { persona_id: 'acme.ava', target_id: 'bluefin.bo', direction: 'right' }],
];

for (const [method, url, body] of jsonRequests) {
  test(`${method} sends a same-origin JSON POST`, async (t) => {
    const fetch = stubFetch(t);
    assert.deepEqual(await api[method](body), { ok: true });
    assert.deepEqual(fetch.mock.calls[0].arguments, [url, {
      method: 'POST', credentials: 'same-origin',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }]);
  });
}

test('accept encodes the request id as one path segment and sends JSON', async (t) => {
  const fetch = stubFetch(t);
  const body = { persona_id: 'bluefin.bo' };
  await api.accept('req /?#+ñ', body);
  assert.deepEqual(fetch.mock.calls[0].arguments, ['/api/connect/req%20%2F%3F%23%2B%C3%B1/accept', {
    method: 'POST', credentials: 'same-origin',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }]);
});

test('reset sends a same-origin POST without a JSON body or content type', async (t) => {
  const fetch = stubFetch(t);
  await api.reset();
  assert.deepEqual(fetch.mock.calls[0].arguments, ['/api/demo/reset', {
    method: 'POST', credentials: 'same-origin',
    headers: { Accept: 'application/json' }, body: undefined,
  }]);
});

test('uploadContext sends file and text as FormData without a JSON content type', async (t) => {
  const fetch = stubFetch(t);
  const file = new File(['Synthetic context'], 'context.txt', { type: 'text/plain' });
  assert.deepEqual(await api.uploadContext({
    personaId: 'acme.ava', visibility: 'shareable', file, text: 'Synthetic notes',
  }), { ok: true });
  const [url, options] = fetch.mock.calls[0].arguments;
  assert.equal(url, '/api/context');
  assert.equal(options.method, 'POST');
  assert.equal(options.credentials, 'same-origin');
  assert.deepEqual(options.headers, { Accept: 'application/json' });
  assert.ok(options.body instanceof FormData);
  assert.deepEqual([...options.body.keys()], ['persona_id', 'visibility', 'file', 'text']);
  assert.equal(options.body.get('persona_id'), 'acme.ava');
  assert.equal(options.body.get('visibility'), 'shareable');
  assert.equal(options.body.get('text'), 'Synthetic notes');
  assert.equal(options.body.get('file').name, 'context.txt');
  assert.equal(await options.body.get('file').text(), 'Synthetic context');
});

test('uploadContext omits absent optional fields', async (t) => {
  const fetch = stubFetch(t);
  await api.uploadContext({ personaId: 'bluefin.bo', visibility: 'private' });
  assert.deepEqual([...fetch.mock.calls[0].arguments[1].body.entries()], [
    ['persona_id', 'bluefin.bo'], ['visibility', 'private'],
  ]);
});

test('uploadContext preserves an explicitly empty text field', async (t) => {
  const fetch = stubFetch(t);
  await api.uploadContext({ personaId: 'acme.ava', visibility: 'private', text: '' });
  const body = fetch.mock.calls[0].arguments[1].body;
  assert.equal(body.has('text'), true);
  assert.equal(body.get('text'), '');
  assert.equal(body.has('file'), false);
});

for (const status of [400, 503]) {
  test(`HTTP ${status} throws a status-only error without reading the response body`, async (t) => {
    const payload = 'SYNTHETIC_PRIVATE_RESPONSE';
    const text = t.mock.fn(async () => payload);
    stubFetch(t, { ok: false, status, text });
    await assert.rejects(api.ask({ persona_id: 'acme.ava', question: 'Synthetic question' }), (error) => {
      assert.ok(error instanceof Error);
      assert.ok(error.message.includes(String(status)));
      assert.ok(!error.message.includes(payload));
      return true;
    });
    assert.equal(text.mock.callCount(), 0);
  });
}

test('a 204 response returns null without reading a body', async (t) => {
  const text = t.mock.fn(async () => { throw new Error('204 body must not be read'); });
  stubFetch(t, { ok: true, status: 204, text });
  assert.equal(await api.reset(), null);
  assert.equal(text.mock.callCount(), 0);
});

test('an empty successful response returns null', async (t) => {
  stubFetch(t, new Response('', { status: 200 }));
  assert.equal(await api.getPersonas(), null);
});

const eventTypes = [
  'connect_request', 'encounter_started', 'pod_status', 'exchange_message',
  'policy_decision', 'private_brief', 'shared_brief', 'encounter_completed',
  'profile_updated', 'deep_dive_started', 'deep_dive_ready', 'agent_decision', 'error',
];

function fakeStream(t) {
  const instances = [];
  class FakeEventSource {
    constructor(url, options) {
      this.url = url;
      this.options = options;
      this.listeners = new Map();
      this.added = [];
      this.removed = [];
      this.closeCalls = 0;
      instances.push(this);
    }

    addEventListener(type, listener) {
      this.added.push([type, listener]);
      if (!this.listeners.has(type)) this.listeners.set(type, new Set());
      this.listeners.get(type).add(listener);
    }

    removeEventListener(type, listener) {
      this.removed.push([type, listener]);
      this.listeners.get(type)?.delete(listener);
    }

    close() { this.closeCalls += 1; }

    dispatch(type, data) {
      for (const listener of this.listeners.get(type) || []) listener({ data });
    }
  }
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'EventSource');
  globalThis.EventSource = FakeEventSource;
  const events = [];
  const close = api.openStream('persona_id=acme.ava', (event) => events.push(event));
  t.after(() => {
    close();
    if (descriptor) Object.defineProperty(globalThis, 'EventSource', descriptor);
    else delete globalThis.EventSource;
  });
  return { source: instances[0], events, close };
}

test('openStream opens the requested credentialed URL and registers every event type', (t) => {
  const { source } = fakeStream(t);
  assert.equal(source.url, '/api/stream?persona_id=acme.ava');
  assert.deepEqual(source.options, { withCredentials: true });
  assert.deepEqual(source.added.map(([type]) => type), eventTypes);
});

for (const type of eventTypes) {
  test(`openStream parses and delivers ${type} JSON`, (t) => {
    const { source, events } = fakeStream(t);
    const event = { type, ts: '2026-11-09T20:00:00Z', encounter_id: 'enc-test', data: { synthetic: true } };
    source.dispatch(type, JSON.stringify(event));
    assert.deepEqual(events, [event]);
  });
}

test('openStream deduplicates an identical type, timestamp and encounter id', (t) => {
  const { source, events } = fakeStream(t);
  const event = { type: 'pod_status', ts: '2026-11-09T20:00:00Z', encounter_id: 'enc-test' };
  source.dispatch(event.type, JSON.stringify(event));
  source.dispatch(event.type, JSON.stringify(event));
  source.dispatch(event.type, JSON.stringify({ ...event, data: { changed: true } }));
  assert.deepEqual(events, [event]);
});

for (const [field, value] of [
  ['type', 'encounter_started'], ['ts', '2026-11-09T20:00:01Z'], ['encounter_id', 'enc-other'],
]) {
  test(`openStream delivers events with a different ${field}`, (t) => {
    const { source, events } = fakeStream(t);
    const first = { type: 'pod_status', ts: '2026-11-09T20:00:00Z', encounter_id: 'enc-test' };
    const second = { ...first, [field]: value };
    source.dispatch(first.type, JSON.stringify(first));
    source.dispatch(second.type, JSON.stringify(second));
    assert.deepEqual(events, [first, second]);
  });
}

test('openStream ignores unknown event types even on a known event listener', (t) => {
  const { source, events } = fakeStream(t);
  const data = JSON.stringify({ type: 'unknown_type', ts: 'synthetic', encounter_id: 'enc-test' });
  source.dispatch('unknown_type', data);
  source.dispatch('pod_status', data);
  assert.equal(source.listeners.has('unknown_type'), false);
  assert.deepEqual(events, []);
});

test('openStream ignores invalid JSON and warns without payload text', (t) => {
  const warn = t.mock.method(console, 'warn', () => {});
  const { source, events } = fakeStream(t);
  const marker = 'SYNTHETIC_PRIVATE_PAYLOAD';
  const invalid = `{"text":"${marker}"`;
  source.dispatch('exchange_message', invalid);
  assert.deepEqual(events, []);
  assert.equal(warn.mock.callCount(), 1);
  for (const call of warn.mock.calls) {
    assert.ok(call.arguments.length > 0);
    for (const argument of call.arguments) {
      assert.ok(!String(argument).includes(marker));
      assert.ok(!String(argument).includes(invalid));
    }
  }
  const valid = { type: 'exchange_message', ts: 'synthetic', encounter_id: 'enc-test' };
  source.dispatch(valid.type, JSON.stringify(valid));
  assert.deepEqual(events, [valid]);
});

test('openStream ignores native connection errors without warning', (t) => {
  const warn = t.mock.method(console, 'warn', () => {});
  const { source, events } = fakeStream(t);
  source.dispatch('error', undefined);
  assert.deepEqual(events, []);
  assert.equal(warn.mock.callCount(), 0);
});

test('openStream close removes every listener and closes the source once', (t) => {
  const { source, events, close } = fakeStream(t);
  const staleListener = source.added[0][1];
  close();
  close();
  assert.deepEqual(source.removed, source.added);
  assert.equal(source.closeCalls, 1);
  for (const listeners of source.listeners.values()) assert.equal(listeners.size, 0);
  const event = { type: 'connect_request', ts: 'synthetic', encounter_id: 'enc-test' };
  source.dispatch(event.type, JSON.stringify(event));
  staleListener({ data: JSON.stringify(event) });
  assert.deepEqual(events, []);
});
