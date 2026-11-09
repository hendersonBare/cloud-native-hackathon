// Live speech transcript for the Capture screen (pure, unit-tested; speech.js feeds it).
// Whichever phone has its mic on is the speaker. Each phone broadcasts what its recognizer hears,
// so both phones hold the same lines. Text is only ever rendered as text nodes, never logged.

export const MAX_LINES = 200;
export const MAX_TEXT = 2000;
// Phrases from the same speaker within this gap join one transcript line (one turn).
export const MERGE_MS = 12000;

/** live: real speech has replaced the scripted playback. listening: who has the mic on, or null. */
export function emptyCapture() {
  return { live: false, lines: [], interim: null, listening: null, error: null };
}

function clean(text) {
  return typeof text === 'string' ? text.replace(/\s+/g, ' ').trim().slice(0, MAX_TEXT) : '';
}

/** 'capture:speech' {from, text, final, at}: a partial (interim) or finished phrase. Mutates state. */
export function applySpeech(state, msg) {
  if (!msg || typeof msg.from !== 'string' || !Number.isFinite(msg.at)) return state;
  const text = clean(msg.text);
  state.live = true;
  if (!msg.final) {
    if (text) state.interim = { from: msg.from, text };
    else if (state.interim?.from === msg.from) state.interim = null;
    return state;
  }
  if (state.interim?.from === msg.from) state.interim = null;
  if (!text) return state;
  const last = state.lines[state.lines.length - 1];
  if (last && last.from === msg.from && msg.at - last.at <= MERGE_MS) {
    last.text = `${last.text} ${text}`.slice(0, MAX_TEXT);
    last.at = msg.at;
  } else {
    state.lines.push({ from: msg.from, text, start: msg.at, at: msg.at });
    if (state.lines.length > MAX_LINES) state.lines.splice(0, state.lines.length - MAX_LINES);
  }
  return state;
}

/** 'capture:mic' {from, on}: a phone turned its mic on or off. Only one phone listens at a time. */
export function applyMic(state, msg) {
  if (!msg || typeof msg.from !== 'string') return state;
  if (msg.on) {
    state.listening = msg.from;
    state.live = true;
  } else if (state.listening === msg.from) {
    state.listening = null;
    if (state.interim?.from === msg.from) state.interim = null;
  }
  return state;
}
