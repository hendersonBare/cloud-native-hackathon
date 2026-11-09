// Live Ask answers must respect the scope the person picked, even though
// AskRequest can't carry it to the gateway: the client fails closed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { liveResult } from '../app/screens/memory.js';

const PERSONAL = 3;
const TEAM = 2;
const ME = 'acme.ava';
const content = {
  questions: [{ level: TEAM, citations: [{ memory_id: 'acme-note-0007' }] }],
};
const found = { answer: 'mock answer', citations: [] };
const answer = (...citations) => ({ answer: 'server answer', citations });
const cite = (memory_id, kind) => ({ memory_id, title: `Title ${memory_id}`, kind, snippet: 'x' });
const OUTSIDE = /outside the selected scope/;

test('Personal scope hides answers built from unknown team memories', () => {
  const result = liveResult(answer(cite('acme-note-9999', 'account_note')), PERSONAL, content, found, ME);
  assert.equal(result.citations.length, 0);
  assert.match(result.answer, OUTSIDE);
});

test('Personal scope hides uncited answers (they cannot be proven personal)', () => {
  assert.match(liveResult(answer(), PERSONAL, content, found, ME).answer, OUTSIDE);
});

test("Personal scope hides a teammate's profile, even a private one", () => {
  for (const id of ['profile-acme.sam-private', 'profile-acme.sam-shareable-2']) {
    assert.match(liveResult(answer(cite(id, 'profile')), PERSONAL, content, found, ME).answer, OUTSIDE, id);
  }
});

test('Personal scope rejects look-alike ids and own ids with the wrong kind', () => {
  for (const c of [
    cite('profile-acme.avalon-private', 'profile'), // another persona whose id starts like mine
    cite('profile-acme.ava-private-x', 'profile'),
    cite('profile-acme.ava-secret', 'profile'),
    cite('profile-acme.ava-private', 'document'),
  ]) {
    assert.match(liveResult(answer(c), PERSONAL, content, found, ME).answer, OUTSIDE, c.memory_id);
  }
});

test('Personal scope treats encounter summaries and follow-ups as unprovable (ids carry no owner)', () => {
  for (const c of [cite('enc-1-summary', 'encounter_summary'), cite('fu-1', 'followup')]) {
    assert.match(liveResult(answer(c), PERSONAL, content, found, ME).answer, OUTSIDE, c.kind);
  }
});

test('Personal scope hides an answer if any citation is not my own profile', () => {
  const mixed = answer(cite('profile-acme.ava-private', 'profile'), cite('acme-doc-0002', 'document'));
  assert.match(liveResult(mixed, PERSONAL, content, found, ME).answer, OUTSIDE);
});

test('Personal scope fails closed when the viewer is unknown', () => {
  assert.match(liveResult(answer(cite('profile-acme.ava-private', 'profile')), PERSONAL, content, found).answer, OUTSIDE);
});

test('Personal scope shows answers cited only from my own profile records', () => {
  const result = liveResult(
    answer(cite('profile-acme.ava-private', 'profile'), cite('profile-acme.ava-shareable-3', 'profile')),
    PERSONAL, content, found, ME,
  );
  assert.equal(result.answer, 'server answer');
  assert.deepEqual(result.citations, [
    { memory_id: 'profile-acme.ava-private', title: 'Title profile-acme.ava-private' },
    { memory_id: 'profile-acme.ava-shareable-3', title: 'Title profile-acme.ava-shareable-3' },
  ]);
});

test('Team scope shows team answers and drops malformed citations', () => {
  const result = liveResult(answer(cite('acme-note-9999', 'account_note'), { memory_id: 7 }, null), TEAM, content, found, ME);
  assert.equal(result.answer, 'server answer');
  assert.deepEqual(result.citations, [{ memory_id: 'acme-note-9999', title: 'Title acme-note-9999' }]);
});

test('a known team memory stays out of a narrower scope whatever kind the server reports', () => {
  assert.match(liveResult(answer(cite('acme-note-0007', 'profile')), PERSONAL, content, found, ME).answer, OUTSIDE);
});

test('the mock verdict wins when the question itself is outside the scope', () => {
  const outside = { answer: 'That memory is outside the selected scope. Include Platform team to search it.', citations: [] };
  const result = liveResult(answer(cite('profile-acme.ava-private', 'profile')), PERSONAL, content, outside, ME);
  assert.equal(result.answer, outside.answer);
});
