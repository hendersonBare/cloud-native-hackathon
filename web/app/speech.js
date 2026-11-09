// Live speech capture with the browser's speech recognition (Chrome and Edge: webkitSpeechRecognition;
// Chrome sends the audio to its speech service). The phone whose mic is on is the speaker. Each phone
// broadcasts what it hears on the bus, so both phones show the same transcript:
//   capture:mic     {from, on}                 a phone turned its mic on or off (broadcast)
//   capture:speech  {from, text, final, at}    an interim or final phrase (broadcast)
//   capture:update  state                      store.capture changed; Capture redraws (local)
// Speech text is never logged and is rendered only as text nodes.
import { emptyCapture, applySpeech, applyMic } from './capture-model.js';

// Let the other phone release the microphone before this one starts listening.
const HANDOVER_MS = 250;
const RESTART_MS = 150;
const MAX_RESTARTS = 8; // within RESTART_WINDOW_MS, then give up rather than loop
const RESTART_WINDOW_MS = 30000;

function recognitionClass() {
  return globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition || null;
}

export function speechSupported() {
  return !!recognitionClass();
}

/** App-lifetime. Returns a controller kept on store.speech: {supported, isOn(), start(), stop(), cleanup()}. */
export function initSpeech({ me, store, bus, lang = 'en-US' }) {
  const state = store.capture || (store.capture = emptyCapture());
  const Recognition = recognitionClass();
  let rec = null;
  let wanted = false;
  let timer = null;
  let restarts = [];
  const changed = () => bus.emitLocal('capture:update', state);
  const cleanups = [];

  cleanups.push(bus.on('capture:speech', (msg) => { applySpeech(state, msg); changed(); }));
  cleanups.push(bus.on('capture:mic', (msg) => {
    applyMic(state, msg);
    // The other phone took the mic: stop here without announcing (it is listening now).
    if (msg?.on && msg.from !== me.id && wanted) halt();
    changed();
  }));

  function fail(kind) {
    state.error = kind;
    stop();
  }

  function make() {
    const r = new Recognition();
    r.lang = lang;
    r.continuous = true;
    r.interimResults = true;
    r.maxAlternatives = 1;
    r.onresult = (event) => {
      if (!wanted) return;
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        bus.emit('capture:speech', {
          from: me.id, text: result[0]?.transcript || '', final: !!result.isFinal, at: Date.now(),
        });
      }
    };
    r.onerror = (event) => {
      const code = event?.error;
      if (code === 'no-speech' || code === 'aborted') return; // onend restarts or it was stopped
      if (code === 'not-allowed' || code === 'service-not-allowed') fail('blocked');
      else if (code === 'audio-capture') fail('no-mic');
      else fail('failed');
      console.warn('Speech recognition stopped', code || 'error');
    };
    // Chrome ends a continuous session after silence or about a minute: start again while wanted.
    r.onend = () => {
      if (!wanted) return;
      const now = Date.now();
      restarts = restarts.filter((t) => now - t < RESTART_WINDOW_MS);
      if (restarts.length >= MAX_RESTARTS) { fail('failed'); return; }
      restarts.push(now);
      clearTimeout(timer);
      timer = setTimeout(() => { if (wanted) begin(); }, RESTART_MS);
    };
    return r;
  }

  function begin() {
    try {
      rec = rec || make();
      rec.start();
    } catch {
      // start() throws InvalidStateError when it is already running; that is fine.
    }
  }

  /** Turn this phone's mic on. Returns false when the browser has no speech recognition. */
  function start() {
    if (!Recognition) return false;
    if (wanted) return true;
    wanted = true;
    restarts = [];
    state.error = null;
    bus.emit('capture:mic', { from: me.id, on: true });
    clearTimeout(timer);
    timer = setTimeout(() => { if (wanted) begin(); }, HANDOVER_MS);
    return true;
  }

  function halt() {
    wanted = false;
    clearTimeout(timer);
    try { rec?.abort(); } catch { /* not running */ }
  }

  /** Turn this phone's mic off and tell the other phone. */
  function stop() {
    const wasOn = wanted || state.listening === me.id;
    halt();
    if (wasOn) bus.emit('capture:mic', { from: me.id, on: false });
    else changed();
  }

  return {
    supported: !!Recognition,
    isOn: () => wanted,
    start,
    stop,
    cleanup() {
      halt();
      for (const close of cleanups) close();
    },
  };
}
