// Stage glue for the swarm panel: show/hide toggle, event source per mode, reset.
import { createSwarmPanel } from './panel.js';
import { CHANNEL, FIXTURE_URL, startLive, startMock } from './driver.js';

const PREF_KEY = 'rapport.swarm';

function readPref() {
  try { return localStorage.getItem(PREF_KEY) !== 'hidden'; } catch { return true; }
}
function writePref(visible) {
  try { localStorage.setItem(PREF_KEY, visible ? 'shown' : 'hidden'); } catch { /* storage blocked */ }
}

/**
 * root: the <aside>; toggle: the presenter-bar button; stage: the .stage element.
 * onLayout runs after the panel is shown or hidden (the stage re-fits the phones).
 * relay receives every live swarm event, so the phones can show the exchange too.
 */
export function initSwarm({ root, toggle, stage, mode, openStream, onLayout, relay }) {
  const panel = createSwarmPanel(root);
  let source = null;

  function start() {
    if (mode === 'live') {
      source = startLive({
        openStream,
        onEvent: (event) => {
          panel.dispatch(event);
          relay?.(event);
        },
      });
    } else {
      const channel = 'BroadcastChannel' in window ? new BroadcastChannel(CHANNEL) : null;
      const driver = startMock({
        channel,
        loadFixture: async () => {
          const response = await fetch(FIXTURE_URL);
          if (!response.ok) throw new Error('fixture unavailable');
          return response.json();
        },
        onEvent: (event) => panel.dispatch(event),
      });
      source = () => { driver.stop(); channel?.close(); };
    }
  }

  function stop() {
    if (typeof source === 'function') source();
    source = null;
  }

  function setVisible(visible, persist = true) {
    root.hidden = !visible;
    stage.classList.toggle('has-swarm', visible);
    toggle.setAttribute('aria-pressed', String(visible));
    toggle.setAttribute('aria-expanded', String(visible));
    toggle.textContent = visible ? 'Hide swarm panel' : 'Show swarm panel';
    if (persist) writePref(visible);
    onLayout?.();
  }

  toggle.addEventListener('click', () => setVisible(root.hidden));
  setVisible(readPref(), false);
  start();

  return {
    /** Reset demo: clear the panel and, in live mode, reopen the stream (its dedupe set resets). */
    reset() {
      stop();
      panel.reset();
      start();
    },
    isVisible: () => !root.hidden,
    panel,
  };
}
