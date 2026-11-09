// One mode: the app checks once whether a gateway answers (detectBackend) and, behind a live
// gateway, falls back to the in-browser client for any feature whose API is missing (withFallback).
import test from 'node:test';
import assert from 'node:assert/strict';
import { detectBackend, isUnavailable, withFallback, PROBE_PATH } from '../app/mode.js';

const json = (body, status = 200) => async () => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});
const httpError = (status) => Object.assign(new Error(`request failed with status ${status}`), { status });

test('detectBackend is live only when the health check answers {"ok": true}', async () => {
  const seen = [];
  const fetchImpl = async (url, init) => { seen.push([url, init.cache]); return json({ ok: true })(); };
  assert.equal(await detectBackend({ fetchImpl }), 'live');
  assert.deepEqual(seen, [[PROBE_PATH, 'no-store']]);
});

test('detectBackend falls back to the browser for 404, wrong bodies, HTML and network errors', async () => {
  assert.equal(await detectBackend({ fetchImpl: json({ ok: true }, 404) }), 'mock');
  assert.equal(await detectBackend({ fetchImpl: json({ ok: false }) }), 'mock');
  assert.equal(await detectBackend({ fetchImpl: json({ status: 'up' }) }), 'mock');
  assert.equal(await detectBackend({ fetchImpl: async () => new Response('<html>', { status: 200 }) }), 'mock');
  assert.equal(await detectBackend({ fetchImpl: async () => { throw new TypeError('Failed to fetch'); } }), 'mock');
  assert.equal(await detectBackend({ fetchImpl: null }), 'mock');
});

test('detectBackend gives up after its timeout', async () => {
  const hang = (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
  });
  assert.equal(await detectBackend({ fetchImpl: hang, timeoutMs: 20 }), 'mock');
});

test('isUnavailable: missing or unreachable APIs, not real errors', () => {
  for (const status of [404, 405, 501, 502, 503, 504]) assert.ok(isUnavailable(httpError(status)), String(status));
  assert.ok(isUnavailable(new TypeError('Failed to fetch')));
  assert.ok(isUnavailable(Object.assign(new Error('x'), { name: 'AbortError' })));
  for (const status of [400, 401, 403, 409, 422, 500]) assert.ok(!isUnavailable(httpError(status)), String(status));
  assert.ok(!isUnavailable(null));
});

function clients() {
  const calls = [];
  const live = {
    view: async (id) => { calls.push(['live.view', id]); return { from: 'live' }; },
    create: async () => { calls.push(['live.create']); throw httpError(404); },
    update: async () => { calls.push(['live.update']); throw httpError(422); },
    exportUrl: (id) => `/api/calendar/export.ics?persona_id=${id}`,
  };
  let made = 0;
  const makeLocal = () => {
    made += 1;
    return {
      view: async (id) => { calls.push(['local.view', id]); return { from: 'local' }; },
      create: async (body) => { calls.push(['local.create', body]); return { from: 'local' }; },
      update: async () => { calls.push(['local.update']); return { from: 'local' }; },
      exportUrl: () => null,
    };
  };
  return { calls, live, makeLocal, made: () => made };
}

test('withFallback uses the live client while it answers', async () => {
  const c = clients();
  const client = withFallback(c.live, c.makeLocal);
  assert.deepEqual(await client.view('acme.ava'), { from: 'live' });
  assert.equal(client.exportUrl('acme.ava'), '/api/calendar/export.ics?persona_id=acme.ava');
  assert.equal(client.isLocal(), false);
  assert.equal(c.made(), 0, 'the in-browser client is only built when needed');
});

test('withFallback switches to the browser on an unavailable API, retries there, and stays there', async () => {
  const c = clients();
  let fellBack = 0;
  const client = withFallback(c.live, c.makeLocal, { onFallback: () => { fellBack += 1; } });
  assert.deepEqual(await client.create({ title: 'Coffee' }), { from: 'local' });
  assert.equal(client.isLocal(), true);
  assert.deepEqual(await client.view('acme.ava'), { from: 'local' });
  assert.equal(client.exportUrl('acme.ava'), null);
  assert.deepEqual(c.calls, [['live.create'], ['local.create', { title: 'Coffee' }], ['local.view', 'acme.ava']]);
  assert.equal(c.made(), 1);
  assert.equal(fellBack, 1);
});

test('withFallback passes real errors through and stays live', async () => {
  const c = clients();
  const client = withFallback(c.live, c.makeLocal);
  await assert.rejects(client.update(), (err) => err.status === 422);
  assert.equal(client.isLocal(), false);
  assert.deepEqual(await client.view('acme.ava'), { from: 'live' });
});

test('withFallback survives being copied with {...client}', async () => {
  const c = clients();
  const copy = { ...withFallback(c.live, c.makeLocal) };
  await copy.create({ title: 'x' });
  assert.equal(copy.isLocal(), true);
});
