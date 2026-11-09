// Conference times are stored as UTC and always shown in America/Denver with the
// zone label (a review rule), so the helpers that do the conversion are pinned here.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  TIMEZONE, formatTime, zoneLabel, formatTimeZoned, formatRange, dayKey, weekdayShort, longDay,
  formatSlot, addDays, noonOf, localToUtc,
} from '../app/time.js';

test('the display zone is America/Denver', () => {
  assert.equal(TIMEZONE, 'America/Denver');
});

test('UTC instants render as Denver wall-clock times with the MST label in November', () => {
  assert.equal(formatTime('2026-11-09T22:30:00Z'), '3:30 PM');
  assert.equal(zoneLabel('2026-11-09T22:30:00Z'), 'MST');
  assert.equal(formatTimeZoned('2026-11-09T22:30:00Z'), '3:30 PM MST');
  assert.equal(formatRange('2026-11-09T22:30:00Z', '2026-11-09T23:00:00Z'), '3:30 PM – 4:00 PM MST');
  assert.equal(formatSlot('2026-11-11T17:00:00Z'), 'Wed 10:00 AM MST');
});

test('the label follows daylight saving time', () => {
  assert.equal(zoneLabel('2026-07-01T18:00:00Z'), 'MDT');
});

test('dayKey uses the Denver date, not the UTC date', () => {
  // 11 PM MST on Monday is already Tuesday in UTC.
  assert.equal(dayKey('2026-11-10T06:00:00Z'), '2026-11-09');
  assert.equal(dayKey('2026-11-10T07:00:00Z'), '2026-11-10');
});

test('weekday and long-day names come from the Denver date', () => {
  assert.equal(weekdayShort('2026-11-10T06:00:00Z'), 'Mon');
  assert.equal(longDay(noonOf('2026-11-09')), 'Monday, November 9, 2026');
});

test('addDays is pure date arithmetic across month ends', () => {
  assert.equal(addDays('2026-11-09', 6), '2026-11-15');
  assert.equal(addDays('2026-11-30', 1), '2026-12-01');
  assert.equal(addDays('2026-11-09', -1), '2026-11-08');
});

test('localToUtc converts seed wall-clock times with the fixed offset', () => {
  assert.equal(localToUtc('2026-11-09', '15:30'), '2026-11-09T22:30:00.000Z');
  assert.equal(localToUtc('2026-11-09', '18:30', '-07:00'), '2026-11-10T01:30:00.000Z');
});

test('invalid input fails loudly instead of rendering "Invalid Date"', () => {
  assert.throws(() => formatTime('not a date'), RangeError);
});
