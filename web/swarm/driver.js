// Event sources for the swarm panel.
//  - live: the gateway's swarm SSE stream (`/api/stream?view=swarm`) through app/api.js.
//  - mock: replays the accept phase of demo-events.json when the phones start an encounter,
//    on the phones' own clock (the bus message carries `startedAt`).
import { SWARM_TYPES } from './model.js';

export const FIXTURE_URL = 'swarm/demo-events.json';
export const CHANNEL = 'rapport-demo';

/** The accept-phase events a swarm viewer may see, with their offsets. Pure. */
export function acceptPhase(fixture) {
  const events = Array.isArray(fixture?.events) ? fixture.events : [];
  return events
    .filter((item) => item?.phase === 'accept' && item.event && SWARM_TYPES.includes(item.event.type))
    .map((item) => ({ at_ms: Number(item.at_ms) || 0, event: item.event }))
    .sort((a, b) => a.at_ms - b.at_ms);
}

/**
 * Live mode. `openStream` is api.openStream; the returned function closes the stream.
 * Only swarm-visible types are forwarded.
 */
export function startLive({ openStream, onEvent }) {
  return openStream('view=swarm', (event) => {
    if (SWARM_TYPES.includes(event.type)) onEvent(event);
  });
}

/**
 * Mock mode. Listens on the phones' BroadcastChannel (messages `{type, data}`):
 *   ui:connect         -> a request was sent
 *   encounter:start    -> replay the fixture from `startedAt`
 *   encounter:declined -> request declined
 *   encounter:done     -> stopped (only when the presenter pressed Stop)
 * Returns { stop(), cancel() }.
 */
export function startMock({
  channel, loadFixture, onEvent, now = Date.now, setTimer = setTimeout, clearTimer = clearTimeout,
}) {
  let timers = [];
  let fixture = null;
  let started = null;
  let stopped = false;

  function cancel() {
    for (const t of timers) clearTimer(t);
    timers = [];
  }
  const stamp = (event) => ({ ...event, ts: new Date(now()).toISOString() });
  const emit = (event) => { if (!stopped) onEvent(stamp(event)); };

  async function replay(startedAt, encounterId) {
    cancel();
    started = encounterId;
    try {
      fixture ||= await loadFixture();
    } catch {
      return;
    }
    if (stopped || started !== encounterId) return;
    const base = Number.isFinite(startedAt) ? startedAt : now();
    for (const { at_ms: offset, event } of acceptPhase(fixture)) {
      const delay = Math.max(0, base + offset - now());
      timers.push(setTimer(() => emit(event), delay));
    }
  }

  function receive(message) {
    const { type, data } = message?.data || {};
    if (typeof type !== 'string') return;
    if (type === 'ui:connect' && data) {
      cancel();
      started = null;
      emit({
        type: 'connect_request', encounter_id: null,
        data: { from_persona_id: data.from, to_persona_id: data.to, initiated_by: data.initiated_by || 'human' },
      });
    } else if (type === 'encounter:start' && data) {
      // Both phones may announce; the responder's broadcast is the only one that crosses the channel.
      const key = data.encounter_id || `${data.initiator}>${data.responder}@${data.startedAt}`;
      if (key !== started) replay(Number(data.startedAt), key);
    } else if (type === 'encounter:declined') {
      cancel();
      started = null;
      emit({ type: 'request_declined', data: {} });
    } else if (type === 'encounter:done' && data?.stopped) {
      cancel();
      emit({ type: 'encounter_stopped', data: {} });
    }
  }

  channel?.addEventListener('message', receive);
  return {
    cancel,
    stop() {
      stopped = true;
      cancel();
      channel?.removeEventListener('message', receive);
    },
  };
}
