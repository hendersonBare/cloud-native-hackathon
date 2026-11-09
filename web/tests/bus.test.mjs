import { after, test } from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';

const windowDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'window');
const NativeBroadcastChannel = globalThis.BroadcastChannel;
const channels = [];

// Keep the real transport, while retaining handles for deterministic cleanup.
globalThis.window = globalThis;
globalThis.BroadcastChannel = class extends NativeBroadcastChannel {
  constructor(name) {
    super(name);
    channels.push(this);
    this.unref();
  }
};
after(() => {
  for (const channel of channels) channel.close();
  globalThis.BroadcastChannel = NativeBroadcastChannel;
  if (windowDescriptor) Object.defineProperty(globalThis, 'window', windowDescriptor);
  else delete globalThis.window;
});

const a = await import('../app/bus.js?a');
const b = await import('../app/bus.js?b');
globalThis.BroadcastChannel = NativeBroadcastChannel;
a.setSelf('acme.ava');
b.setSelf('bluefin.bo');

for (const method of ['emit', 'emitLocal']) {
  test(`${method} synchronously delivers data and sender metadata`, (t) => {
    const calls = [];
    const type = `test:${method}:local`;
    const data = { encounter_id: 'enc-test' };
    t.after(a.on(type, (...args) => calls.push(args)));
    a[method](type, data);
    assert.deepEqual(calls, [[data, { type, data, from: 'acme.ava' }]]);
  });

  test(`unsubscribe stops ${method} delivery`, () => {
    let calls = 0;
    const type = `test:${method}:unsubscribe`;
    const unsubscribe = a.on(type, () => calls++);
    a[method](type, {});
    unsubscribe();
    unsubscribe();
    a[method](type, {});
    assert.equal(calls, 1);
  });

  test(`wildcard listeners receive ${method} events and can unsubscribe`, () => {
    const calls = [];
    const unsubscribe = a.on('*', (data, message) => calls.push([data, message.type]));
    try {
      a[method](`test:${method}:wildcard`, { count: 1 });
      unsubscribe();
      a[method](`test:${method}:wildcard`, { count: 2 });
      assert.deepEqual(calls, [[{ count: 1 }, `test:${method}:wildcard`]]);
    } finally {
      unsubscribe();
    }
  });
}

for (const throwingType of ['test:throw', '*']) {
  test(`a throwing ${throwingType} listener does not stop later listeners`, (t) => {
    const warn = t.mock.method(console, 'warn', () => {});
    const calls = [];
    t.after(a.on(throwingType, () => { throw new Error('synthetic listener failure'); }));
    t.after(a.on('test:throw', () => calls.push('typed')));
    t.after(a.on('*', () => calls.push('wildcard')));
    assert.doesNotThrow(() => a.emitLocal('test:throw', {}));
    assert.deepEqual(calls, ['typed', 'wildcard']);
    assert.equal(warn.mock.callCount(), 1);
  });
}

function nextMessage(t, bus, type) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`No broadcast received for ${type}`)), 1000);
    const unsubscribe = bus.on(type, (data, message) => {
      clearTimeout(timeout);
      unsubscribe();
      resolve({ data, message });
    });
    t.after(() => { clearTimeout(timeout); unsubscribe(); });
  });
}

for (const [sender, receiver, from] of [[a, b, 'acme.ava'], [b, a, 'bluefin.bo']]) {
  test(`emit broadcasts from ${from} to the other phone`, async (t) => {
    assert.equal(channels.length, 2);
    const type = `test:broadcast:${from}`;
    const data = { encounter_id: 'enc-broadcast' };
    const delivered = nextMessage(t, receiver, type);
    sender.emit(type, data);
    assert.deepEqual(await delivered, { data, message: { type, data, from } });
  });
}

test('emitLocal never reaches the other phone', async (t) => {
  const calls = [];
  t.after(b.on('test:private', (data) => calls.push(data)));
  a.emitLocal('test:private', { local: true });
  // A real broadcast acts as a delivery barrier, proving the receiver is active.
  const delivered = nextMessage(t, b, 'test:barrier');
  a.emit('test:barrier', {});
  await delivered;
  await delay(50);
  assert.deepEqual(calls, []);
});
