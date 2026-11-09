import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  CONFIG_URL, REDACTED, SDK_INTEGRITY, SDK_URL, SDK_VERSION, initOptions, installQueue, personaFrom,
  scrubFragment, scrubFullUrl, scrubQuery, scrubUrlAttributes, startRum, usableConfig,
} from '../app/rum.js';

const ENABLED = {
  enabled: true,
  serviceName: 'rapport-web',
  serviceVersion: 'abc1234',
  environment: 'hackathon',
  endpoint: { url: 'https://ingress.example.aws.dash0.com', authToken: 'auth_website_test_placeholder' },
};

function fakeDom() {
  const appended = [];
  return {
    win: {},
    doc: {
      head: { append: (el) => appended.push(el) },
      createElement: (tagName) => ({ tagName }),
    },
    appended,
  };
}

function respond(body, { ok = true } = {}) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return { ok, json: async () => body };
  };
  return { fetchImpl, calls };
}

test('the SDK is pinned to one version and checked with Subresource Integrity', () => {
  assert.match(SDK_VERSION, /^\d+\.\d+\.\d+$/);
  assert.equal(SDK_URL, `https://unpkg.com/@dash0/sdk-web@${SDK_VERSION}/dist/dash0.iife.js`);
  assert.match(SDK_INTEGRITY, /^sha256-[A-Za-z0-9+/]{43}=$/);
});

test('scrubQuery keeps ID-like values and redacts free text such as the talk search', () => {
  assert.equal(scrubQuery('persona_id=acme.ava&q=ebpf+and+security'), `persona_id=acme.ava&q=${REDACTED}`);
  assert.equal(scrubQuery('?persona=bluefin.bo&live=1&secret=x'), `?persona=bluefin.bo&live=1&secret=${REDACTED}`);
  assert.equal(scrubQuery(''), '');
  assert.equal(scrubQuery(undefined), undefined);
});

test('scrubFragment redacts the query inside a hash route', () => {
  assert.equal(scrubFragment('#/person?id=bluefin.bo&note=hi'), `#/person?id=bluefin.bo&note=${REDACTED}`);
  assert.equal(scrubFragment('/home'), '/home');
});

test('scrubFullUrl redacts the query and the hash route, and drops both when it cannot parse the URL', () => {
  assert.equal(
    scrubFullUrl('https://rapport.cnh.radarhq.io/api/talks?persona_id=acme.ava&q=find+me+ebpf'),
    `https://rapport.cnh.radarhq.io/api/talks?persona_id=acme.ava&q=${REDACTED}`,
  );
  assert.equal(
    scrubFullUrl('https://rapport.cnh.radarhq.io/phone.html?persona=acme.ava#/find?with=bluefin.bo&x=y'),
    `https://rapport.cnh.radarhq.io/phone.html?persona=acme.ava#/find?with=bluefin.bo&x=${REDACTED}`,
  );
  assert.equal(scrubFullUrl('https://rapport.cnh.radarhq.io/healthz'), 'https://rapport.cnh.radarhq.io/healthz');
  assert.equal(scrubFullUrl('/api/talks?q=private words#frag'), '/api/talks');
});

test('scrubUrlAttributes scrubs url.full, url.query and url.fragment and keeps the rest', () => {
  const out = scrubUrlAttributes({
    'url.full': 'https://h.example/api/calendar/agenda?persona_id=acme.ava&q=lunch',
    'url.path': '/api/calendar/agenda',
    'url.query': 'persona_id=acme.ava&q=lunch',
    'url.fragment': '/tag?tag=ebpf',
  });
  assert.deepEqual(out, {
    'url.full': `https://h.example/api/calendar/agenda?persona_id=acme.ava&q=${REDACTED}`,
    'url.path': '/api/calendar/agenda',
    'url.query': `persona_id=acme.ava&q=${REDACTED}`,
    'url.fragment': `/tag?tag=${REDACTED}`,
  });
  assert.equal('url.query' in scrubUrlAttributes({ 'url.full': 'https://h.example/' }), false);
});

test('usableConfig accepts an enabled https config and rejects anything else', () => {
  assert.equal(usableConfig(ENABLED), ENABLED);
  const local = { ...ENABLED, endpoint: { url: 'http://localhost:4318', authToken: 't' } };
  assert.equal(usableConfig(local), local);
  for (const bad of [
    null,
    { enabled: false },
    { ...ENABLED, enabled: 'true' },
    { ...ENABLED, endpoint: undefined },
    { ...ENABLED, endpoint: { url: 'http://ingress.example.aws.dash0.com', authToken: 't' } },
    { ...ENABLED, endpoint: { url: 'javascript:alert(1)', authToken: 't' } },
    { ...ENABLED, endpoint: { url: 'not a url', authToken: 't' } },
    { ...ENABLED, endpoint: { url: ENABLED.endpoint.url, authToken: '' } },
    { ...ENABLED, endpoint: { url: ENABLED.endpoint.url } },
  ]) {
    assert.equal(usableConfig(bad), null);
  }
});

test('personaFrom reads only persona IDs from the phone URL', () => {
  assert.equal(personaFrom('?persona=bluefin.bo&mock=1'), 'bluefin.bo');
  assert.equal(personaFrom('?persona=Ava%20Smith'), null);
  assert.equal(personaFrom('?mock=1'), null);
  assert.equal(personaFrom(''), null);
});

test('initOptions uses the SDK option names, tags the page and persona, and scrubs URLs', () => {
  const options = initOptions(
    { ...ENABLED, endpoint: { ...ENABLED.endpoint, dataset: 'rapport' } },
    { page: 'phone', persona: 'acme.ava' },
  );
  assert.equal(options.serviceName, 'rapport-web');
  assert.equal(options.serviceVersion, 'abc1234');
  assert.equal(options.environment, 'hackathon');
  assert.deepEqual(options.endpoint, { ...ENABLED.endpoint, dataset: 'rapport' });
  assert.deepEqual(options.additionalSignalAttributes, { 'rapport.page': 'phone', 'rapport.persona_id': 'acme.ava' });
  assert.equal(options.urlAttributeScrubber, scrubUrlAttributes);
  assert.deepEqual(options.pageViewInstrumentation, { includeParts: ['HASH'] });
  assert.equal('sessionRecording' in options, false);

  const bare = initOptions({ enabled: true, endpoint: { url: 'https://x.example', authToken: 't' } }, { page: 'stage' });
  assert.deepEqual(Object.keys(bare).sort(), [
    'additionalSignalAttributes', 'endpoint', 'pageViewInstrumentation', 'serviceName', 'urlAttributeScrubber',
  ]);
  assert.deepEqual(bare.additionalSignalAttributes, { 'rapport.page': 'stage' });
  assert.deepEqual(bare.endpoint, { url: 'https://x.example', authToken: 't' });
});

test('installQueue records calls the way the SDK replays them, and keeps an existing dash0', () => {
  const win = {};
  const dash0 = installQueue(win);
  dash0('init', { serviceName: 'x' });
  assert.equal(win.dash0, dash0);
  assert.equal(dash0._v, 1);
  assert.ok(dash0._t instanceof Date);
  assert.deepEqual(dash0._q, [['init', { serviceName: 'x' }]]);
  assert.equal(installQueue(win), dash0);
});

test('startRum queues init and adds the pinned SDK script when the gateway has RUM configured', async () => {
  const { win, doc, appended } = fakeDom();
  const { fetchImpl, calls } = respond(ENABLED);
  assert.equal(await startRum({ page: 'phone', persona: 'bluefin.bo', win, doc, fetchImpl }), true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, CONFIG_URL);
  assert.equal(calls[0].init.credentials, 'same-origin');
  const [name, options] = win.dash0._q[0];
  assert.equal(name, 'init');
  assert.equal(options.additionalSignalAttributes['rapport.persona_id'], 'bluefin.bo');
  assert.equal(appended.length, 1);
  assert.deepEqual(appended[0], {
    tagName: 'script',
    src: SDK_URL,
    integrity: SDK_INTEGRITY,
    crossOrigin: 'anonymous',
    referrerPolicy: 'no-referrer',
    defer: true,
  });
});

test('startRum loads nothing when RUM is off, the request fails or the answer is unusable', async () => {
  const cases = [
    respond({ enabled: false }),
    respond(ENABLED, { ok: false }),
    respond({ ...ENABLED, endpoint: { url: 'http://ingress.example.aws.dash0.com', authToken: 't' } }),
    { fetchImpl: async () => { throw new TypeError('offline'); } },
    { fetchImpl: async () => ({ ok: true, json: async () => { throw new SyntaxError('not json'); } }) },
  ];
  for (const { fetchImpl } of cases) {
    const { win, doc, appended } = fakeDom();
    assert.equal(await startRum({ page: 'stage', win, doc, fetchImpl }), false);
    assert.equal(win.dash0, undefined);
    assert.equal(appended.length, 0);
  }
});

test('startRum does nothing without a browser, or when dash0 is already set up', async () => {
  const { fetchImpl, calls } = respond(ENABLED);
  assert.equal(await startRum({ page: 'stage', win: undefined, doc: undefined, fetchImpl }), false);
  const { win, doc, appended } = fakeDom();
  win.dash0 = () => {};
  assert.equal(await startRum({ page: 'stage', win, doc, fetchImpl }), false);
  assert.equal(calls.length, 0);
  assert.equal(appended.length, 0);
});

test('both pages load the RUM boot script in their head', () => {
  for (const page of ['index.html', 'phone.html']) {
    const html = readFileSync(new URL(`../${page}`, import.meta.url), 'utf8');
    const head = html.slice(0, html.indexOf('</head>'));
    assert.match(head, /<script type="module" src="rum-boot\.js"><\/script>/, page);
  }
});
