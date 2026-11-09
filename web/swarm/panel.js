// Swarm panel controller: owns the state, renders it into `root`, and appends only new
// timeline entries so the aria-live region announces each new line once.
import { h } from '../app/ui.js';
import { createState, reduce } from './model.js';
import { STATUS_LABEL, entryNode, headerNodes, laneNodes } from './view.js';

export function createSwarmPanel(root) {
  let state = createState();
  const rendered = new Map(); // entry id -> node

  const title = h('h2', { id: 'swarm-title', class: 'sw-title' }, 'Agents on Kubernetes');
  const status = h('p', { class: 'sw-status', role: 'status', 'data-status': 'idle' }, STATUS_LABEL.idle);
  const header = h('div', { class: 'sw-header' });
  const lanes = h('div', { class: 'sw-lanes' });
  const timeline = h('ol', {
    class: 'sw-timeline', 'aria-live': 'polite', 'aria-relevant': 'additions', 'aria-label': 'Exchange timeline',
    tabindex: '0',
  });
  root.setAttribute('aria-labelledby', 'swarm-title');
  root.replaceChildren(
    h('div', { class: 'sw-top' }, title, status),
    header, lanes,
    h('h3', { class: 'sw-eyebrow' }, 'Exchange timeline'),
    timeline);

  function draw() {
    status.textContent = STATUS_LABEL[state.status] || STATUS_LABEL.idle;
    status.setAttribute('data-status', state.status);
    header.replaceChildren(...headerNodes(state));
    lanes.replaceChildren(...laneNodes(state));

    const live = new Set(state.timeline.map((entry) => entry.id));
    for (const [id, node] of rendered) {
      if (!live.has(id)) {
        node.remove();
        rendered.delete(id);
      }
    }
    for (const entry of state.timeline) {
      if (rendered.has(entry.id)) continue;
      const node = entryNode(entry);
      rendered.set(entry.id, node);
      timeline.append(node);
    }
    timeline.scrollTop = timeline.scrollHeight;
  }

  draw();
  return {
    /** Feed one GatewayEvent (or a presenter-side synthetic one). */
    dispatch(event) {
      const next = reduce(state, event);
      if (next === state) return false;
      state = next;
      draw();
      return true;
    },
    reset() {
      state = createState();
      draw();
    },
    getState: () => state,
  };
}
