// h() is the XSS guarantee the security review relies on: every string becomes a
// text node or an attribute value, never parsed HTML. A tiny fake DOM is enough
// to prove that without a browser or any dependency.
import test from 'node:test';
import assert from 'node:assert/strict';

class FakeNode {
  constructor() { this.childNodes = []; }
  append(...nodes) {
    for (const n of nodes) {
      const node = n instanceof FakeNode ? n : new FakeText(String(n));
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
  constructor(tag, ns) {
    super();
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.namespaceURI = ns || null;
    this.attrs = new Map();
    this.listeners = {};
    this.dataset = {};
    this.style = { setProperty: (k, v) => { this.style[k] = v; } };
  }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  set innerHTML(_) { throw new Error('innerHTML must never be used'); }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  findAll(pred, out = []) {
    for (const c of this.children) { if (pred(c)) out.push(c); c.findAll(pred, out); }
    return out;
  }
}

globalThis.Node = FakeNode;
globalThis.document = {
  createElement: (tag) => new FakeElement(tag),
  createElementNS: (ns, tag) => new FakeElement(tag, ns),
  createTextNode: (data) => new FakeText(data),
};

const { h, icon, bottomNav, topbar } = await import('../app/ui.js');

const PAYLOAD = '<img src=x onerror="alert(1)"><script>alert(2)</script>';

test('h() turns string children into text nodes, never elements', () => {
  const el = h('p', null, PAYLOAD);
  assert.equal(el.childNodes.length, 1);
  assert.equal(el.childNodes[0].nodeType, 3);
  assert.equal(el.childNodes[0].data, PAYLOAD);
  assert.equal(el.children.length, 0);
});

test('h() keeps attribute values verbatim through setAttribute', () => {
  const el = h('a', { title: PAYLOAD, href: '#/home' });
  assert.equal(el.getAttribute('title'), PAYLOAD);
  assert.equal(el.getAttribute('href'), '#/home');
});

test('h() flattens arrays, stringifies numbers and skips null, false and true', () => {
  const el = h('div', null, ['a', ['b', 3]], null, false, true, undefined);
  assert.deepEqual(el.childNodes.map((c) => c.data), ['a', 'b', '3']);
});

test('h() handles class, boolean attributes, dataset, style and event handlers', () => {
  const onClick = () => {};
  const el = h('button', {
    class: 'btn', disabled: true, hidden: false, title: null,
    dataset: { id: 'x' }, style: { color: 'red', '--s': '1' }, onClick,
  });
  assert.equal(el.getAttribute('class'), 'btn');
  assert.equal(el.getAttribute('disabled'), '');
  assert.equal(el.getAttribute('hidden'), null);
  assert.equal(el.getAttribute('title'), null);
  assert.equal(el.dataset.id, 'x');
  assert.equal(el.style.color, 'red');
  assert.equal(el.style['--s'], '1');
  assert.deepEqual(el.listeners.click, [onClick]);
});

test('icon() is decorative by default and labelled when asked', () => {
  const plain = icon('check');
  assert.equal(plain.namespaceURI, 'http://www.w3.org/2000/svg');
  assert.equal(plain.getAttribute('aria-hidden'), 'true');
  const labelled = icon('check', { label: 'Allowed' });
  assert.equal(labelled.getAttribute('role'), 'img');
  assert.equal(labelled.getAttribute('aria-label'), 'Allowed');
  assert.throws(() => icon('nope'), /unknown icon/);
});

test('bottomNav marks the tab that owns the current route', () => {
  const current = (route) => bottomNav(route)
    .findAll((el) => el.getAttribute('aria-current') === 'page')
    .map((el) => el.getAttribute('href'));
  assert.deepEqual(current('home'), ['#/home']);
  assert.deepEqual(current('exchange'), ['#/people']);
  assert.deepEqual(current('person'), ['#/people']);
  assert.deepEqual(current('people'), ['#/people']);
  assert.deepEqual(current('tag'), ['#/live']);
  assert.deepEqual(current('progress'), ['#/progress']);
  // Calendar has no tab of its own; it opens from Home's Up next.
  assert.deepEqual(current('calendar'), ['#/home']);
});

test('bottomNav has Progress and no Calendar tab', () => {
  const hrefs = bottomNav('home').findAll((el) => el.tagName === 'A').map((el) => el.getAttribute('href'));
  assert.deepEqual(hrefs, ['#/home', '#/live', '#/memory', '#/progress', '#/people']);
});

test('topbar renders a labelled back link and the title as text', () => {
  const bar = topbar({ back: 'live', backLabel: 'Back to transcript', title: PAYLOAD });
  const [link] = bar.findAll((el) => el.tagName === 'A');
  assert.equal(link.getAttribute('href'), '#/live');
  assert.equal(link.getAttribute('aria-label'), 'Back to transcript');
  const [title] = bar.findAll((el) => el.tagName === 'H1');
  assert.equal(title.textContent, PAYLOAD);
  assert.equal(title.children.length, 0);
});
