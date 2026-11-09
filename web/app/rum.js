// Dash0 website monitoring (RUM) for the stage and the phone pages.
//
// No token lives in git: the page asks the gateway for its RUM settings at load time
// (GET /api/rum-config, filled from the optional `dash0-rum` Secret). When the gateway has none,
// the page runs exactly as before and loads nothing from Dash0.
//
// The SDK is Dash0's script-tag build (@dash0/sdk-web, pinned, with Subresource Integrity), set up
// the way its official snippet does it: a `dash0` queue function first, then the deferred script.
// Same-origin fetches get a `traceparent` header from the SDK, so a click in the browser continues
// into the gateway's trace, and from there into the Encounter and both delegate pods.
//
// Privacy (AGENTS.md section 4): no session replay is loaded, and URL query values that can carry
// what a person typed (for example the talk search `q`) are replaced with REDACTED before they
// become span attributes. Only ID-like parameters are kept.

export const CONFIG_URL = '/api/rum-config';
export const SDK_VERSION = '0.18.1';
export const SDK_URL = `https://unpkg.com/@dash0/sdk-web@${SDK_VERSION}/dist/dash0.iife.js`;
// sha256 of the file above, checked against unpkg's ?meta listing and a local hash of the download.
export const SDK_INTEGRITY = 'sha256-hor29KHsCT0/sBqiYuTMv41GExqsvyhQO0mTKLl/8xQ=';
export const SERVICE_NAME = 'rapport-web';
export const REDACTED = 'REDACTED';

// Query and hash-route parameters whose values are IDs, flags or dates, never free text.
const KEEP_PARAMS = new Set([
  'persona', 'persona_id', 'live', 'mock', 'view', 'id', 'with', 'from', 'request', 'start', 'end', 'days',
]);
const PERSONA_ID = /^[a-z0-9-]+\.[a-z0-9-]+$/;

/** 'persona_id=acme.ava&q=ebpf talks' -> 'persona_id=acme.ava&q=REDACTED'. Keeps a leading '?'. */
export function scrubQuery(query) {
  if (typeof query !== 'string' || query === '') return query;
  const prefix = query.startsWith('?') ? '?' : '';
  const out = new URLSearchParams();
  for (const [key, value] of new URLSearchParams(query.slice(prefix.length))) {
    out.append(key, KEEP_PARAMS.has(key) ? value : REDACTED);
  }
  return prefix + out.toString();
}

/** Hash routes carry their own query: '#/person?id=bluefin.bo&q=x' -> '#/person?id=bluefin.bo&q=REDACTED'. */
export function scrubFragment(fragment) {
  if (typeof fragment !== 'string') return fragment;
  const i = fragment.indexOf('?');
  return i < 0 ? fragment : `${fragment.slice(0, i)}?${scrubQuery(fragment.slice(i + 1))}`;
}

/** Scrubs a whole URL. One that can't be parsed keeps only what comes before its query and hash. */
export function scrubFullUrl(full) {
  if (typeof full !== 'string') return full;
  let url;
  try {
    url = new URL(full);
  } catch {
    return full.split(/[?#]/)[0];
  }
  if (url.search) url.search = scrubQuery(url.search);
  if (url.hash) url.hash = scrubFragment(url.hash);
  return url.toString();
}

/** The SDK's urlAttributeScrubber: runs on every url.* and page.url.* attribute record. */
export function scrubUrlAttributes(attributes) {
  const out = { ...attributes };
  out['url.full'] = scrubFullUrl(attributes['url.full']);
  if ('url.query' in attributes) out['url.query'] = scrubQuery(attributes['url.query']);
  if ('url.fragment' in attributes) out['url.fragment'] = scrubFragment(attributes['url.fragment']);
  return out;
}

/** The gateway's answer, or null unless it is enabled and complete. Only https endpoints (or localhost). */
export function usableConfig(config) {
  if (!config || config.enabled !== true) return null;
  const endpoint = config.endpoint;
  if (!endpoint || typeof endpoint.url !== 'string' || typeof endpoint.authToken !== 'string') return null;
  if (!endpoint.authToken) return null;
  let url;
  try {
    url = new URL(endpoint.url);
  } catch {
    return null;
  }
  const local = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  if (url.protocol !== 'https:' && !(local && url.protocol === 'http:')) return null;
  return config;
}

/** The persona from a phone URL (?persona=acme.ava), only when it looks like a persona ID. */
export function personaFrom(search) {
  const persona = new URLSearchParams(search || '').get('persona');
  return persona && PERSONA_ID.test(persona) ? persona : null;
}

/** The options for dash0('init', ...), from the gateway's config. Names follow the SDK's InitOptions. */
export function initOptions(config, { page, persona } = {}) {
  const endpoint = { url: config.endpoint.url, authToken: config.endpoint.authToken };
  if (config.endpoint.dataset) endpoint.dataset = config.endpoint.dataset;
  const attributes = { 'rapport.page': page || 'unknown' };
  if (persona) attributes['rapport.persona_id'] = persona; // telemetry.ATTR_PERSONA
  const options = {
    serviceName: config.serviceName || SERVICE_NAME,
    endpoint,
    additionalSignalAttributes: attributes,
    urlAttributeScrubber: scrubUrlAttributes,
    // The phone app routes with the hash (#/home, #/person?id=...), so each screen is its own page view.
    pageViewInstrumentation: { includeParts: ['HASH'] },
  };
  if (config.serviceVersion) options.serviceVersion = config.serviceVersion;
  if (config.environment) options.environment = config.environment;
  return options;
}

/** Defines the `dash0` queue function, like Dash0's script-tag snippet. The SDK replays the queue once it loads. */
export function installQueue(win) {
  if (win.dash0) return win.dash0;
  const queue = [];
  // The SDK replays each entry by index ([name, ...args]), so plain arrays work like the snippet's `arguments`.
  const dash0 = (...args) => {
    queue.push(args);
  };
  dash0._t = new Date();
  dash0._v = 1;
  dash0._q = queue;
  win.dash0 = dash0;
  return dash0;
}

/** The pinned SDK <script>, checked with Subresource Integrity and loaded without a referrer. */
export function sdkScript(doc) {
  const script = doc.createElement('script');
  script.src = SDK_URL;
  script.integrity = SDK_INTEGRITY;
  script.crossOrigin = 'anonymous';
  script.referrerPolicy = 'no-referrer';
  script.defer = true;
  return script;
}

/**
 * Starts RUM on this page if the gateway has it configured. Resolves to true when the SDK was set up,
 * false otherwise. Never rejects: monitoring must not break the demo.
 */
export async function startRum({
  page,
  persona = null,
  win = globalThis.window,
  doc = globalThis.document,
  fetchImpl = globalThis.fetch,
} = {}) {
  if (!win || !doc?.head || typeof fetchImpl !== 'function') return false;
  if (win.dash0) return false; // already set up on this page
  let config;
  try {
    const response = await fetchImpl(CONFIG_URL, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (!response.ok) return false;
    config = usableConfig(await response.json());
  } catch {
    return false;
  }
  if (!config) return false;
  installQueue(win)('init', initOptions(config, { page, persona }));
  doc.head.append(sdkScript(doc));
  return true;
}
