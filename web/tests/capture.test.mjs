// The Capture screen's scripted hallway conversation (web/app/screens/live.js) and the speaker
// sheet behind it (tag.js). Two presenters read one script in the demo, so both phones must show
// the same words, each from its own side.
import test from 'node:test';
import assert from 'node:assert/strict';
import { CONTENT as CAPTURE } from '../app/screens/live.js';
import { CONTENT as SHEET } from '../app/screens/tag.js';

const SWAP = { you: 's2', s2: 'you' };

test('both phones show the same hallway conversation with the speakers swapped', () => {
  const ava = CAPTURE['acme.ava'].lines;
  const bo = CAPTURE['bluefin.bo'].lines;
  assert.ok(ava.length > 3, 'Capture starts with all but 3 lines shown, then reveals the rest');
  assert.deepEqual(bo, ava.map(([who, text]) => [SWAP[who], text]));
});

test("the speaker sheet previews the other person's first line from the same conversation", () => {
  for (const id of ['acme.ava', 'bluefin.bo']) {
    const [, first] = CAPTURE[id].lines.find(([who]) => who === 's2');
    assert.equal(SHEET[id].title, 'Hallway conversation', id);
    assert.equal(SHEET[id].transcript, first, id);
    assert.equal(SHEET[id].lang, 'en', id);
  }
});

// ---- Real speech: capture-model.js (pure) and speech.js (fake recognizer, two phones on one bus) ----
import { emptyCapture, applySpeech, applyMic, MERGE_MS } from '../app/capture-model.js';
import { initSpeech } from '../app/speech.js';

test('a final phrase becomes a line and clears that speaker\'s interim text', () => {
  const s = emptyCapture();
  applySpeech(s, { from: 'acme.ava', text: 'we use', final: false, at: 1000 });
  assert.deepEqual(s.interim, { from: 'acme.ava', text: 'we use' });
  assert.equal(s.live, true);
  applySpeech(s, { from: 'acme.ava', text: '  we use  eBPF ', final: true, at: 2000 });
  assert.equal(s.interim, null);
  assert.deepEqual(s.lines, [{ from: 'acme.ava', text: 'we use eBPF', start: 2000, at: 2000 }]);
});

test('phrases from the same speaker join one turn; a new speaker or a long gap starts a line', () => {
  const s = emptyCapture();
  applySpeech(s, { from: 'bluefin.bo', text: 'We are migrating.', final: true, at: 0 });
  applySpeech(s, { from: 'bluefin.bo', text: 'Tracing matters.', final: true, at: MERGE_MS });
  applySpeech(s, { from: 'acme.ava', text: 'Acme can help.', final: true, at: MERGE_MS + 1 });
  applySpeech(s, { from: 'acme.ava', text: 'Later.', final: true, at: 2 * MERGE_MS + 2 });
  assert.deepEqual(s.lines.map((l) => [l.from, l.text]), [
    ['bluefin.bo', 'We are migrating. Tracing matters.'],
    ['acme.ava', 'Acme can help.'],
    ['acme.ava', 'Later.'],
  ]);
});

test('empty or malformed speech never adds a line', () => {
  const s = emptyCapture();
  applySpeech(s, { from: 'acme.ava', text: '   ', final: true, at: 1 });
  applySpeech(s, { from: 'acme.ava', text: 'no time', final: true });
  applySpeech(s, { text: 'no speaker', final: true, at: 1 });
  applySpeech(s, null);
  assert.deepEqual(s.lines, []);
});

test('only the phone that turned its mic on can turn "listening" off', () => {
  const s = emptyCapture();
  applyMic(s, { from: 'acme.ava', on: true });
  applyMic(s, { from: 'bluefin.bo', on: true });
  assert.equal(s.listening, 'bluefin.bo');
  applyMic(s, { from: 'acme.ava', on: false });
  assert.equal(s.listening, 'bluefin.bo');
  applyMic(s, { from: 'bluefin.bo', on: false });
  assert.equal(s.listening, null);
});

class FakeRecognition {
  static all = [];
  constructor() { this.started = 0; this.aborted = 0; FakeRecognition.all.push(this); }
  start() { this.started += 1; this.running = true; }
  abort() { this.aborted += 1; this.running = false; this.onend?.(); }
  stop() { this.running = false; this.onend?.(); }
  hear(text, isFinal) {
    const result = Object.assign([{ transcript: text }], { isFinal });
    this.onresult?.({ resultIndex: 0, results: [result] });
  }
}

// Both phones' buses joined, as BroadcastChannel joins the two iframes on the stage.
function joinedBuses() {
  const phones = [];
  const make = () => {
    const listeners = new Map();
    const bus = {
      dispatch(type, data) { for (const fn of [...(listeners.get(type) || [])]) fn(data); },
      on(type, fn) {
        if (!listeners.has(type)) listeners.set(type, new Set());
        listeners.get(type).add(fn);
        return () => listeners.get(type).delete(fn);
      },
      emitLocal(type, data) { bus.dispatch(type, data); },
      emit(type, data) { for (const b of phones) b.dispatch(type, data); },
    };
    phones.push(bus);
    return bus;
  };
  return [make(), make()];
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test('speech heard on one phone shows on both, and one mic at a time', async (t) => {
  const saved = Object.getOwnPropertyDescriptor(globalThis, 'webkitSpeechRecognition');
  globalThis.webkitSpeechRecognition = FakeRecognition;
  t.after(() => { if (saved) Object.defineProperty(globalThis, 'webkitSpeechRecognition', saved); else delete globalThis.webkitSpeechRecognition; });
  const [avaBus, boBus] = joinedBuses();
  const avaStore = {};
  const boStore = {};
  const ava = initSpeech({ me: { id: 'acme.ava' }, store: avaStore, bus: avaBus });
  const bo = initSpeech({ me: { id: 'bluefin.bo' }, store: boStore, bus: boBus });
  t.after(() => { ava.cleanup(); bo.cleanup(); });
  assert.equal(ava.supported, true);

  ava.start();
  assert.equal(boStore.capture.listening, 'acme.ava', 'the other phone knows whose mic is on');
  await wait(300);
  const avaRec = FakeRecognition.all.at(-1);
  assert.equal(avaRec.started, 1);
  avaRec.hear('We use zero-code', false);
  assert.deepEqual(boStore.capture.interim, { from: 'acme.ava', text: 'We use zero-code' });
  avaRec.hear('We use zero-code eBPF tracing.', true);
  for (const store of [avaStore, boStore]) {
    assert.deepEqual(store.capture.lines.map((l) => [l.from, l.text]), [['acme.ava', 'We use zero-code eBPF tracing.']]);
  }

  bo.start();
  assert.equal(ava.isOn(), false, "Bo's mic turns Ava's off");
  assert.equal(avaRec.aborted, 1);
  assert.equal(avaStore.capture.listening, 'bluefin.bo');
  await wait(300);
  assert.equal(avaRec.started, 1, "Ava's recognizer is not restarted after the handover");
  bo.stop();
  assert.equal(avaStore.capture.listening, null);
});

test('a blocked microphone stops listening and says why', async (t) => {
  const saved = Object.getOwnPropertyDescriptor(globalThis, 'webkitSpeechRecognition');
  globalThis.webkitSpeechRecognition = FakeRecognition;
  t.after(() => { if (saved) Object.defineProperty(globalThis, 'webkitSpeechRecognition', saved); else delete globalThis.webkitSpeechRecognition; });
  const [bus] = joinedBuses();
  const store = {};
  const speech = initSpeech({ me: { id: 'acme.ava' }, store, bus });
  t.after(() => speech.cleanup());
  speech.start();
  await wait(300);
  FakeRecognition.all.at(-1).onerror({ error: 'not-allowed' });
  assert.equal(speech.isOn(), false);
  assert.equal(store.capture.error, 'blocked');
  assert.equal(store.capture.listening, null);
});
