// Without a gateway, a right swipe replays what the gateway would send for it, from the same
// scripted events the swarm panel and the gateway's mock mode use (contracts/demo-events.json,
// copied to web/swarm/demo-events.json): the deep dive, the agent's decision, then the
// agent-initiated connect request. Only pairs the script covers have steps; the rest connect
// directly. Pure, so it is unit-tested.

import script from '../swarm/demo-events.json' with { type: 'json' };

const SWIPE_TYPES = new Set(['deep_dive_started', 'deep_dive_ready', 'agent_decision']);

/**
 * Steps for `from` swiping right on `to`: [{ at_ms, type, event }] in time order, ending with a
 * { type: 'connect_request' } step when the script has the agent send one. Empty if not scripted.
 */
export function swipeScript(from, to, events = script.events) {
  const steps = [];
  for (const item of events || []) {
    if (item?.phase !== 'swipe' || !item.event) continue;
    const { event } = item;
    const data = event.data || {};
    if (SWIPE_TYPES.has(event.type) && event.persona_id === from && data.target_persona_id === to) {
      steps.push({ at_ms: item.at_ms, type: event.type, event });
    } else if (event.type === 'connect_request' && data.from_persona_id === from && data.to_persona_id === to) {
      steps.push({ at_ms: item.at_ms, type: 'connect_request', event });
    }
  }
  return steps.sort((a, b) => a.at_ms - b.at_ms);
}
