// "Your context" on the Memory screen: the shared context model (what the agent carries, saving
// to the gateway or to the phone) and the editor that changes it, rendered on a tiny fake DOM.
import { describe, it, before, after } from 'node:test';
import assert from 'node:assert/strict';
import {
  currentContext, validateDraft, fromProfile, saveContext, MAX_NOTE_CHARS, MAX_FILE_BYTES,
} from '../app/context-model.js';

const AVA = { id: 'acme.ava', orgName: 'Acme Observability' };
const BO = { id: 'bluefin.bo', orgName: 'Bluefin Health' };
const ctxFor = (me = AVA, mode = 'mock', store = {}) => ({ me, mode, store });
const file = (name, size = 10) => ({ name, size }); // no text()/arrayBuffer(): the phone never reads it
const httpError = (status) => Object.assign(new Error(`failed with status ${status}`), { status });
const PROFILE = {
  persona_id: 'acme.ava',
  shareable: { visibility: 'shareable', headline: 'Pilots with hospital platform teams', interests: ['eBPF', 'HIPAA'] },
  private: { visibility: 'private', headline: 'Budget call is in Q1', interests: [] },
};

describe('context model', () => {
  it('starts from the persona seed, in the seed line language', () => {
    const ava = currentContext(ctxFor(AVA));
    assert.deepEqual(ava.topics, ['eBPF tracing', 'OpenTelemetry', 'Healthcare', 'Observability']);
    assert.match(ava.workingOn, /hospital network rollout/);
    assert.equal(ava.visibility, 'shareable');
    assert.equal(ava.note, '');
    assert.equal(currentContext(ctxFor(BO)).lang, 'es');
  });

  it("follows Profile's visibility until the person saves one here", () => {
    assert.equal(currentContext(ctxFor(AVA, 'mock', { profile: { visibility: 'private' } })).visibility, 'private');
  });

  it("ignores a saved context that isn't this phone's person", () => {
    const store = { context: { personaId: 'bluefin.bo', note: 'not mine', topics: ['x'] } };
    const now = currentContext(ctxFor(AVA, 'mock', store));
    assert.equal(now.note, '');
    assert.notDeepEqual(now.topics, ['x']);
  });

  it('checks a draft before sending it', () => {
    assert.match(validateDraft({ text: '   ' }), /Write something/);
    assert.match(validateDraft({ text: 'x'.repeat(MAX_NOTE_CHARS + 1) }), /under 4,000/);
    assert.match(validateDraft({ file: file('cv.docx') }), /\.pdf, \.md or \.txt/);
    assert.match(validateDraft({ file: file('cv.pdf', MAX_FILE_BYTES + 1) }), /over 2 MB/);
    assert.equal(validateDraft({ text: 'Looking for pilots' }), null);
    assert.equal(validateDraft({ file: file('CV.PDF') }), null);
  });

  it('reads the chosen visibility from the profile and keeps what it leaves out', () => {
    const prior = { topics: ['old'], workingOn: 'old line' };
    assert.deepEqual(fromProfile(PROFILE, 'shareable', prior),
      { topics: ['eBPF', 'HIPAA'], workingOn: 'Pilots with hospital platform teams' });
    assert.deepEqual(fromProfile(PROFILE, 'private', prior), { topics: ['old'], workingOn: 'Budget call is in Q1' });
    assert.deepEqual(fromProfile(null, 'shareable', prior), prior);
    const many = { shareable: { headline: ' ', interests: ['a', 2, '', ...'bcdefghij'] } };
    assert.deepEqual(fromProfile(many, 'shareable', prior).topics, ['a', ...'bcdefgh']);
  });

  it('without a gateway, saves on the phone and keeps only the file name', async () => {
    const ctx = ctxFor(AVA, 'mock');
    const result = await saveContext(ctx, { text: '  Meeting hospital teams  ', file: file('cv.pdf'), visibility: 'private' });
    assert.deepEqual(result, { ok: true, savedTo: 'phone' });
    const now = currentContext(ctx);
    assert.equal(now.note, 'Meeting hospital teams');
    assert.equal(now.filename, 'cv.pdf');
    assert.equal(now.visibility, 'private');
    assert.equal(now.savedTo, 'phone');
    assert.ok(!('file' in ctx.store.context), 'the file object is not kept');
  });

  it('with a gateway, uploads and shows what the agent made of it', async () => {
    const calls = [];
    const ctx = ctxFor(AVA, 'live');
    const upload = async (args) => { calls.push(args); return PROFILE; };
    const result = await saveContext(ctx, { text: 'Pilots', visibility: 'shareable' }, { upload });
    assert.deepEqual(result, { ok: true, savedTo: 'agent' });
    assert.deepEqual(calls, [{ personaId: 'acme.ava', visibility: 'shareable', file: undefined, text: 'Pilots' }]);
    const now = currentContext(ctx);
    assert.deepEqual(now.topics, ['eBPF', 'HIPAA']);
    assert.equal(now.workingOn, 'Pilots with hospital platform teams');
    assert.equal(now.lang, undefined);
  });

  it("falls back to the phone when the gateway doesn't serve the API", async () => {
    for (const error of [httpError(404), httpError(405), httpError(501)]) {
      const ctx = ctxFor(AVA, 'live');
      const result = await saveContext(ctx, { text: 'Pilots' }, { upload: async () => { throw error; } });
      assert.deepEqual(result, { ok: true, savedTo: 'phone' }, String(error.status || error.name));
    }
  });

  it('reports a real refusal and changes nothing', async (t) => {
    t.mock.method(console, 'warn', () => {});
    // A gateway that is there but failing (5xx, network) is an error to show, not a reason to go local.
    const refusals = [
      [httpError(429), /busy/], [httpError(413), /too large/], [httpError(415), /\.pdf, \.md and \.txt/],
      [httpError(500), /could not save/], [httpError(503), /could not save/], [new TypeError('network'), /could not save/],
    ];
    for (const [error, pattern] of refusals) {
      const ctx = ctxFor(AVA, 'live');
      const result = await saveContext(ctx, { text: 'Pilots' }, { upload: async () => { throw error; } });
      assert.equal(result.ok, false);
      assert.match(result.message, pattern, String(error.status || error.name));
      assert.equal(ctx.store.context, undefined);
    }
    for (const [message] of console.warn.mock.calls.map((c) => c.arguments)) assert.doesNotMatch(String(message), /Pilots/);
  });

  it('never sends an invalid draft', async () => {
    let called = false;
    const result = await saveContext(ctxFor(AVA, 'live'), { text: '' }, { upload: async () => { called = true; } });
    assert.equal(result.ok, false);
    assert.equal(called, false);
  });
});

// ------------------------------------------------------------ the Memory screen editor

class FakeNode {
  constructor() { this.childNodes = []; this.parent = null; }
  append(...nodes) {
    for (const n of nodes) {
      const node = n instanceof FakeNode ? n : new FakeText(String(n));
      node.parent = this;
      this.childNodes.push(node);
    }
  }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }
}
class FakeText extends FakeNode {
  constructor(data) { super(); this.nodeType = 3; this.data = data; }
  get textContent() { return this.data; }
}
class FakeElement extends FakeNode {
  constructor(tag) {
    super();
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.attrs = new Map();
    this.listeners = {};
    this.dataset = {};
    this.hidden = false;
    this.value = '';
    this.style = { setProperty: (k, v) => { this.style[k] = v; } };
  }
  set textContent(text) { this.childNodes = []; this.append(String(text)); }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }
  set innerHTML(_) { throw new Error('innerHTML must never be used'); }
  replaceChildren(...nodes) { this.childNodes = []; this.append(...nodes); }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  fire(type, event = {}) { for (const fn of this.listeners[type] || []) fn({ preventDefault() {}, target: this, ...event }); }
  focus() { focused = this; }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get lastElementChild() { return this.children.at(-1) || null; }
  get classList() {
    const el = this;
    const list = () => (el.getAttribute('class') || '').split(/\s+/).filter(Boolean);
    return {
      contains: (name) => list().includes(name),
      toggle(name, force) {
        const on = force === undefined ? !list().includes(name) : force;
        el.setAttribute('class', [...list().filter((c) => c !== name), ...(on ? [name] : [])].join(' '));
      },
    };
  }
  all(pred, out = []) {
    for (const c of this.children) { if (pred(c)) out.push(c); c.all(pred, out); }
    return out;
  }
  find(cls) { return this.all((el) => el.classList.contains(cls))[0] || null; }
  querySelector(tag) { return this.all((el) => el.tagName === tag.toUpperCase())[0] || null; }
}

let focused = null;
let saved = null;
let render;
const FAKES = {
  Node: FakeNode,
  document: {
    createElement: (tag) => new FakeElement(tag),
    createElementNS: (_ns, tag) => new FakeElement(tag),
    createTextNode: (data) => new FakeText(data),
  },
};
const flush = async () => { for (let i = 0; i < 4; i += 1) await new Promise((r) => setImmediate(r)); };

function setup(store = {}) {
  const cleanups = [];
  const ctx = { me: AVA, mode: 'mock', store, onCleanup: (fn) => cleanups.push(fn) };
  const root = render(ctx);
  const s = {
    root, ctx,
    edit: root.find('memory-context-edit'),
    card: () => root.find('memory-context'),
    leave: () => { for (const fn of cleanups.splice(0)) fn(); },
  };
  return s;
}

describe('Memory screen: Your context', () => {
  before(async () => {
    saved = Object.fromEntries(Object.keys(FAKES).map((k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
    for (const [k, v] of Object.entries(FAKES)) Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true });
    ({ render } = await import('../app/screens/memory.js'));
  });
  after(() => {
    for (const [k, desc] of Object.entries(saved || {})) {
      if (desc) Object.defineProperty(globalThis, k, desc);
      else delete globalThis[k];
    }
  });

  it('shows what the agent carries, with an Edit button', (t) => {
    const s = setup();
    t.after(s.leave);
    assert.match(s.card().textContent, /eBPF tracing/);
    assert.match(s.card().textContent, /Shared with people you meet/);
    assert.equal(s.edit.getAttribute('aria-expanded'), 'false');
    assert.match(s.edit.textContent, /Edit/);
  });

  it('edits, saves on the phone without a gateway, and shows the note', async (t) => {
    const s = setup();
    t.after(s.leave);
    s.edit.fire('click');
    assert.equal(s.edit.getAttribute('aria-expanded'), 'true');
    const note = s.card().querySelector('textarea');
    assert.ok(note, 'the editor has a text box');
    assert.equal(focused, note, 'the text box takes focus');
    note.value = 'Meeting hospital platform teams';
    note.fire('input');
    const [, privateChoice] = s.card().all((el) => el.getAttribute('type') === 'radio');
    privateChoice.fire('change', { target: { checked: true } });
    s.card().find('memory-context-form').fire('submit');
    await flush();
    assert.equal(s.edit.getAttribute('aria-expanded'), 'false');
    assert.match(s.card().textContent, /Meeting hospital platform teams/);
    assert.match(s.card().textContent, /Private to your agent/);
    assert.match(s.card().textContent, /Saved on this phone/);
    assert.equal(focused, s.edit, 'focus returns to Edit');
    assert.equal(s.ctx.store.context.note, 'Meeting hospital platform teams');
  });

  it('shows a problem inline and keeps the editor open', async (t) => {
    const s = setup();
    t.after(s.leave);
    s.edit.fire('click');
    s.card().find('memory-context-form').fire('submit');
    await flush();
    assert.equal(s.edit.getAttribute('aria-expanded'), 'true');
    const status = s.card().find('memory-context-status');
    assert.match(status.textContent, /Write something/);
    assert.ok(status.classList.contains('is-error'));
  });

  it('Cancel discards the draft', (t) => {
    const s = setup();
    t.after(s.leave);
    s.edit.fire('click');
    const note = s.card().querySelector('textarea');
    note.value = 'draft that goes away';
    note.fire('input');
    s.card().find('memory-context-cancel').fire('click');
    assert.equal(s.edit.getAttribute('aria-expanded'), 'false');
    assert.doesNotMatch(s.card().textContent, /draft that goes away/);
    s.edit.fire('click');
    assert.equal(s.card().querySelector('textarea').value, '');
  });
});
