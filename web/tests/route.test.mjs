import test from 'node:test';
import assert from 'node:assert/strict';
import { ROUTES, parseHash, hashFor } from '../app/route.js';

test('parseHash reads the route name and query params', () => {
  assert.deepEqual(parseHash('#/person?id=bluefin.bo'), { name: 'person', params: { id: 'bluefin.bo' } });
});

test('parseHash accepts a hash without the leading slash', () => {
  assert.equal(parseHash('#memory').name, 'memory');
});

test('parseHash falls back to home for empty or unknown routes', () => {
  for (const hash of ['', '#', '#/', '#/nope', '#/__proto__', undefined]) {
    assert.deepEqual(parseHash(hash), { name: 'home', params: {} });
  }
});

test('every route parses to itself', () => {
  for (const name of ROUTES) assert.equal(parseHash(`#/${name}`).name, name);
});

test('hashFor encodes params and round-trips through parseHash', () => {
  const hash = hashFor('person', { id: 'bluefin.bo', note: 'a&b c' });
  assert.equal(hash, '#/person?id=bluefin.bo&note=a%26b+c');
  assert.deepEqual(parseHash(hash), { name: 'person', params: { id: 'bluefin.bo', note: 'a&b c' } });
  assert.equal(hashFor('home'), '#/home');
});
