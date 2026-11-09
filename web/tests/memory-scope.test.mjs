// Live Ask answers must respect the scope the person picked, even though
// AskRequest can't carry it to the gateway: the client fails closed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { liveResult } from '../app/screens/memory.js';

const PERSONAL = 3;
const TEAM = 2;
const content = {
  questions: [{ level: TEAM, citations: [{ memory_id: 'acme-note-0007' }] }],
};
const found = { answer: 'mock answer', citations: [] };
const answer = (...citations) => ({ answer: 'server answer', citations });
const cite = (memory_id, kind) => ({ memory_id, title: `Title ${memory_id}`, kind, snippet: 'x' });

test('Personal scope hides answers built from unknown team memories', () => {
  const result = liveResult(answer(cite('acme-note-9999', 'account_note')), PERSONAL, content, found);
  assert.equal(result.citations.length, 0);
  assert.match(result.answer, /outside the selected scope/);
});

test('Personal scope hides uncited answers (they cannot be proven personal)', () => {
  assert.match(liveResult(answer(), PERSONAL, content, found).answer, /outside the selected scope/);
});

test('Personal scope hides an answer if any citation is not personal', () => {
  const mixed = answer(cite('ava-profile', 'profile'), cite('acme-doc-0002', 'document'));
  assert.match(liveResult(mixed, PERSONAL, content, found).answer, /outside the selected scope/);
});

test('Personal scope shows answers whose citations are all personal', () => {
  const result = liveResult(answer(cite('ava-profile', 'profile'), cite('enc-1', 'encounter_summary')), PERSONAL, content, found);
  assert.equal(result.answer, 'server answer');
  assert.deepEqual(result.citations, [
    { memory_id: 'ava-profile', title: 'Title ava-profile' },
    { memory_id: 'enc-1', title: 'Title enc-1' },
  ]);
});

test('Team scope shows team answers and drops malformed citations', () => {
  const result = liveResult(answer(cite('acme-note-9999', 'account_note'), { memory_id: 7 }, null), TEAM, content, found);
  assert.equal(result.answer, 'server answer');
  assert.deepEqual(result.citations, [{ memory_id: 'acme-note-9999', title: 'Title acme-note-9999' }]);
});

test('a known team memory stays out of a narrower scope even if the server tags it personal', () => {
  const result = liveResult(answer(cite('acme-note-0007', 'profile')), PERSONAL, content, found);
  assert.match(result.answer, /outside the selected scope/);
});

test('the mock verdict wins when the question itself is outside the scope', () => {
  const outside = { answer: 'That memory is outside the selected scope. Include Platform team to search it.', citations: [] };
  assert.equal(liveResult(answer(cite('ava-profile', 'profile')), PERSONAL, content, outside).answer, outside.answer);
});
