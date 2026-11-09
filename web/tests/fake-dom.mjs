// A tiny fake DOM for the swarm panel tests. install() puts it on globalThis and returns a
// function that restores whatever was there, so other test files in the same process are unaffected.

export class FakeNode {
  constructor() { this.childNodes = []; this.parentNode = null; }
  append(...nodes) {
    for (const n of nodes) {
      const node = n instanceof FakeNode ? n : new FakeText(String(n));
      node.parentNode = this;
      this.childNodes.push(node);
    }
  }
  replaceChildren(...nodes) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = [];
    this.append(...nodes);
  }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.childNodes = this.parentNode.childNodes.filter((c) => c !== this);
    this.parentNode = null;
  }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }
  set textContent(value) { this.replaceChildren(String(value)); }
}

export class FakeText extends FakeNode {
  constructor(data) { super(); this.nodeType = 3; this.data = data; }
  get textContent() { return this.data; }
  set textContent(value) { this.data = String(value); }
}

export class FakeElement extends FakeNode {
  constructor(tag, ns) {
    super();
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.namespaceURI = ns || null;
    this.attrs = new Map();
    this.listeners = {};
    this.dataset = {};
    this.hidden = false;
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.style = { setProperty: (k, v) => { this.style[k] = v; } };
  }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  click() { for (const fn of this.listeners.click || []) fn({ target: this }); }
  set innerHTML(_) { throw new Error('innerHTML must never be used'); }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get classList() {
    const el = this;
    const list = () => (el.getAttribute('class') || '').split(/\s+/).filter(Boolean);
    return {
      contains: (name) => list().includes(name),
      toggle(name, force) {
        const has = list().includes(name);
        const on = force === undefined ? !has : force;
        const next = list().filter((c) => c !== name);
        if (on) next.push(name);
        el.setAttribute('class', next.join(' '));
      },
    };
  }
  findAll(pred, out = []) {
    for (const c of this.children) { if (pred(c)) out.push(c); c.findAll(pred, out); }
    return out;
  }
  /** Elements whose class list includes `name`. */
  byClass(name) { return this.findAll((el) => el.classList.contains(name)); }
}

export function install() {
  const saved = { Node: globalThis.Node, document: globalThis.document };
  globalThis.Node = FakeNode;
  globalThis.document = {
    createElement: (tag) => new FakeElement(tag),
    createElementNS: (ns, tag) => new FakeElement(tag, ns),
    createTextNode: (data) => new FakeText(data),
  };
  return () => {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  };
}
