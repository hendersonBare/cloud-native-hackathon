// The app has a single mode. It uses the gateway when one answers on this origin (the
// deployed page), and otherwise runs every feature in the browser, with the two phones
// kept in sync over a BroadcastChannel (a plain static server, a laptop with no cluster).
// Features whose own API is missing behind a live gateway fall back on their own
// (withFallback), so every feature always works.

export const PROBE_PATH = '/healthz';
export const PROBE_TIMEOUT_MS = 1500;

/** 'live' when the gateway's health check answers {"ok": true}, else 'mock'. Never throws. */
export async function detectBackend({ fetchImpl = globalThis.fetch, timeoutMs = PROBE_TIMEOUT_MS } = {}) {
  if (typeof fetchImpl !== 'function') return 'mock';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(PROBE_PATH, {
      signal: controller.signal, cache: 'no-store', headers: { Accept: 'application/json' },
    });
    if (!response.ok) return 'mock';
    const body = await response.json().catch(() => null);
    return body?.ok === true ? 'live' : 'mock';
  } catch {
    return 'mock';
  } finally {
    clearTimeout(timer);
  }
}

// Statuses that mean "this gateway doesn't serve this feature": the route isn't mounted, so the
// request changed nothing and can safely be replayed in the browser. Transient trouble (502, 503,
// 504, a dropped connection, a timeout) is NOT one of them: switching for good on a blip would
// leave this phone writing only to its own replica, and a 504 may come after the server wrote.
const UNAVAILABLE = new Set([404, 405, 501]);

/** True when an error from a live client means the feature's route isn't there at all. */
export function isUnavailable(error) {
  return error != null && UNAVAILABLE.has(error.status);
}

/**
 * Wrap a live client so the first call that shows its route isn't mounted (404/405/501)
 * switches this phone to the in-browser client (`makeLocal()`) for the rest of the session
 * and retries that call there. Every other error, transient ones included, passes through. Synchronous methods use whichever client
 * is active when they're called.
 */
export function withFallback(live, makeLocal, { onFallback } = {}) {
  let local = null;
  const active = () => local || live;
  const fallBack = () => {
    if (!local) {
      local = makeLocal();
      onFallback?.();
    }
    return local;
  };
  // A function, not a getter: callers copy clients with {...client}, which would freeze a getter.
  const wrapped = { isLocal: () => local !== null };
  for (const [name, fn] of Object.entries(live)) {
    if (typeof fn !== 'function' || name in wrapped) continue;
    wrapped[name] = (...args) => {
      if (local) return callOn(local, name, args);
      let result;
      try {
        result = fn(...args);
      } catch (error) {
        if (isUnavailable(error)) return callOn(fallBack(), name, args);
        throw error;
      }
      if (!result || typeof result.then !== 'function') return result;
      return result.catch((error) => {
        if (!isUnavailable(error)) throw error;
        return callOn(fallBack(), name, args);
      });
    };
  }
  wrapped.active = active;
  return wrapped;
}

function callOn(client, name, args) {
  const fn = client[name];
  if (typeof fn !== 'function') return undefined;
  return fn.apply(client, args);
}
