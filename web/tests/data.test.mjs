import test from 'node:test';
import assert from 'node:assert/strict';
import { DEMO, PEOPLE, VIEWS, peerOf, person } from '../app/data.js';

test('person includes the known organization name and role', () => {
  const ava = person('acme.ava');
  assert.equal(ava.id, 'acme.ava');
  assert.equal(ava.orgName, 'Acme Observability');
  assert.equal(ava.role, 'Solutions Engineer · Acme Observability');
});

test('person returns null for an unknown id', () => {
  assert.equal(person('unknown.person'), null);
});

test('peerOf maps the two demo personas to each other', () => {
  assert.equal(peerOf('acme.ava'), 'bluefin.bo');
  assert.equal(peerOf('bluefin.bo'), 'acme.ava');
});

for (const side of ['left', 'right']) {
  test(`the ${side} demo persona exists in PEOPLE`, () => {
    assert.ok(Object.hasOwn(PEOPLE, DEMO[side]));
    assert.equal(PEOPLE[DEMO[side]].id, DEMO[side]);
  });

  test(`the ${side} demo persona has home content`, () => {
    const home = VIEWS[DEMO[side]]?.home;
    assert.ok(home);
    assert.equal(typeof home.event, 'string');
    assert.ok(home.event.length > 0);
    assert.ok(home.live.title.length > 0);
    assert.ok(home.upNext.length > 0);
  });

  test(`all ${side} home opportunities resolve to people`, () => {
    const opportunities = VIEWS[DEMO[side]].home.opportunities;
    assert.ok(opportunities.length > 0);
    for (const opportunity of opportunities) {
      assert.ok(person(opportunity.id), opportunity.id);
    }
  });

  test(`the ${side} home deck includes the peer`, () => {
    assert.ok(VIEWS[DEMO[side]].home.opportunities.some(({ id }) => id === peerOf(DEMO[side])));
  });

  test(`the ${side} agreed meeting references a known person`, () => {
    assert.ok(person(VIEWS[DEMO[side]].home.agreed.with));
  });
}
