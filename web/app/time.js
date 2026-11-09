// Time display for the conference. The calendar API stores and returns aware UTC
// (ISO 8601 with an offset); the phones always display America/Denver with its
// zone label, as the review rules require. Pure, so it is unit-tested.

export const TIMEZONE = 'America/Denver';

const timeFormat = new Intl.DateTimeFormat('en-US', { timeZone: TIMEZONE, hour: 'numeric', minute: '2-digit' });
const zoneFormat = new Intl.DateTimeFormat('en-US', { timeZone: TIMEZONE, timeZoneName: 'short' });
const keyFormat = new Intl.DateTimeFormat('en-CA', { timeZone: TIMEZONE, year: 'numeric', month: '2-digit', day: '2-digit' });
const weekdayFormat = new Intl.DateTimeFormat('en-US', { timeZone: TIMEZONE, weekday: 'short' });
const longDayFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: TIMEZONE, weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
});

function asDate(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) throw new RangeError('Invalid date');
  return date;
}

/** '2026-11-09T22:30:00Z' -> '3:30 PM' (Denver wall clock). */
export function formatTime(value) {
  return timeFormat.format(asDate(value));
}

/** The zone label at that instant, e.g. 'MST'. */
export function zoneLabel(value = new Date()) {
  const part = zoneFormat.formatToParts(asDate(value)).find((p) => p.type === 'timeZoneName');
  return part ? part.value : 'MT';
}

/** '3:30 PM MST'. */
export function formatTimeZoned(value) {
  return `${formatTime(value)} ${zoneLabel(value)}`;
}

/** '3:30 – 4:00 PM MST' style range for one event. */
export function formatRange(start, end) {
  return `${formatTime(start)} – ${formatTime(end)} ${zoneLabel(start)}`;
}

/** Local (Denver) calendar date of an instant: 'YYYY-MM-DD'. */
export function dayKey(value) {
  return keyFormat.format(asDate(value));
}

/** 'Mon' for an instant, in Denver. */
export function weekdayShort(value) {
  return weekdayFormat.format(asDate(value));
}

/** 'Monday, November 9, 2026' for an instant, in Denver. */
export function longDay(value) {
  return longDayFormat.format(asDate(value));
}

/** 'Wed 10:00 AM MST'. */
export function formatSlot(value) {
  return `${weekdayShort(value)} ${formatTimeZoned(value)}`;
}

/** 'YYYY-MM-DD' + n days (pure date arithmetic, no time zone involved). */
export function addDays(key, n) {
  const [y, m, d] = key.split('-').map(Number);
  const date = new Date(Date.UTC(y, m - 1, d + n));
  return date.toISOString().slice(0, 10);
}

/** Noon UTC on a local date key: a safe instant for naming that day in Denver. */
export function noonOf(key) {
  return new Date(`${key}T19:00:00Z`);
}

/**
 * Wall clock in Denver -> aware UTC ISO string, using a fixed offset such as '-07:00'
 * (the conference week is all MST, and the seed carries its offset).
 */
export function localToUtc(key, hhmm, utcOffset = '-07:00') {
  return new Date(`${key}T${hhmm}:00${utcOffset}`).toISOString();
}
