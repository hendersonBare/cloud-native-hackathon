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
