# rapport_calendar

The per-person agenda for the conference week: conference talks, meetings that agents propose between people, and
personal events. It is a FastAPI `APIRouter` (prefix `/api/calendar`) that the gateway mounts in-process, plus a
standalone dev server that serves the same router and, optionally, the `web/` folder.

State is in memory (the gateway runs one replica) and starts from `data/seed.json`, which has a byte-identical copy
at `web/mock/calendar-seed.json` for the JS mock. `reset()` restores it.

## Endpoints

All under `/api/calendar`. Errors are `{"detail": "<code>"}`; validation errors are FastAPI's 422.

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `` | `persona_id`, `start?` (YYYY-MM-DD), `days?` (1..14, default 7) | `CalendarView` |
| POST | `/events` | `CreateEventBody` | 201 `CreateEventResult` (with overlap `conflicts`) |
| PATCH | `/events/{event_id}` | `UpdateEventBody` | `CalendarEvent` |
| DELETE | `/events/{event_id}` | `persona_id` | 204 |
| POST | `/events/{event_id}/respond` | `RespondBody` | `CalendarEvent` (my copy) |
| PUT | `/conference-mode` | `ConferenceModeBody` | `ConferenceModeState` |
| GET | `/agenda` | `persona_id`, `q?` (<= 100 chars) | `AgendaView` |
| POST | `/talks` | `AddTalkBody` | 201 `CreateEventResult` |
| POST | `/propose` | `ProposeBody` | 201 (200 when `created: false`) `MeetingProposal` |
| GET | `/freebusy` | `persona_id`, `start`, `end` (aware ISO, <= 14 days) | `FreeBusy` |
| GET | `/export.ics` | `persona_id` | `text/calendar`, `Content-Disposition: attachment` |

The standalone app also serves `GET /healthz` -> `{"ok": true, "version": ...}`.

Models are in `models.py`. They live here because `rapport_common` is integrator-owned: **CONTRACT CHANGE REQUEST**
to promote them into `rapport_common.models`. They reuse `TalkHit` and `SharedBrief`.

## Rules in short

- Times on the wire are ISO 8601 with an offset, stored and returned as UTC (`2026-11-09T22:30:00Z`); naive times
  are a 422. The display zone is `America/Denver` (MST all week). The seed's `day` + `HH:MM` wall-clock times are
  converted with its fixed `utc_offset`.
- Every person in `rapport_common.names.personas()` has a calendar; unknown ids are 404 `unknown_persona`.
  Another person's event id is 404 `event_not_found` (its existence is never revealed).
- Create/update times must lie inside the conference week, end after they start and last at most 12 hours (422).
  At most 200 non-declined events per person (409 `calendar_full`); declined meeting copies do not count and only
  the 20 newest are kept.
- `capture` can change on any of my events. Title, time and location only on `source: user` events (409
  `not_editable`). Delete only works for `user` and `conference` events (409 `not_deletable`).
- Meetings: accepting sets my response; when everyone accepted, **every** copy becomes `confirmed`. Declining makes
  every copy `declined`, which frees the slot for both people. Settled copies get a templated note ("Confirmed by
  both", "Declined by <name>"). Non-meetings are 409 `not_a_meeting`, closed ones 409
  `meeting_closed`.
- Conference mode is a per-person flag (seed: Ava and Bo). Talks added afterwards get `capture = conference_mode`;
  existing events are not rewritten.
- Propose is deterministic: the first 15-minute slot, Monday to Friday, 09:00-18:00 local (it must end by 18:00),
  that overlaps no non-declined event of either person. Only the invitee's free/busy time is read; titles and
  locations are templated, so no free text crosses companies. No slot is 409 `no_mutual_slot`. Asking again for the
  same pair returns the existing future meeting (`created: false`). A `not_before` in the past is raised to the
  server clock, so a meeting is never offered in the past.
- Agenda: for companies that run agents it asks the briefer (`GET {briefer}/v1/talks`, 3 second timeout, answer
  validated as `TalkSearchResult`). On any error, timeout or malformed answer, for other companies, or when
  `RAPPORT_CALENDAR_AGENDA=seed`, it answers from the seed agenda (case-insensitive word-prefix match on title,
  track, room and speakers) with `source: "seed"`.

- Time zone: responses that list events or times (`CalendarView`, `AgendaView`, `CreateEventResult`,
  `MeetingProposal`, `FreeBusy`) carry `timezone: "America/Denver"`. `PATCH /events/{id}` and `/respond` return the bare
  `CalendarEvent`; take the zone label from the `CalendarView` the client already holds.
- Privacy of searches: the agenda `q` is never put on a span or log. The briefer call is excluded from the httpx
  instrumentation, the server span's URL attributes are rewritten to the bare path, and the standalone server runs with
  `access_log=False`. **Integrator:** the gateway that mounts this router needs its own uvicorn access log off (or a
  filter that strips query strings), because `GET /api/calendar/agenda?q=...` carries the search text.

## Configuration

| Variable | Meaning |
|---|---|
| `RAPPORT_CALENDAR_AGENDA=seed` | Never call a briefer; use the seed agenda. |
| `RAPPORT_CALENDAR_NOW` | ISO 8601 time with an offset that pins the server clock for rehearsals. |
| `RAPPORT_WEB_DIR` | Standalone only: serve this folder at `/` after the API routes. |
| `RAPPORT_VERSION` | Reported by `/healthz`. |
| `BRIEFER_URL_<ORG>` | Local override of a briefer URL (`rapport_common.names.briefer_url`). |

## Mounting in the gateway

```python
from rapport_calendar.api import get_service, router as calendar_router

app.include_router(calendar_router)  # before the StaticFiles mount

# POST /api/demo/reset
get_service().reset()

# when a delegate pushes a shared_brief for a person
await get_service().record_shared_brief(brief, counterparty_persona_id)
```

`record_shared_brief` treats the brief's `suggested_talk` as an id only: it looks the talk up on the agenda and adds
the agenda's own copy (title, room, time) as a `proposed` talk (source `agent`, note "Suggested by your agents"), and
only when the talk lies inside the conference week. It returns the event, or `None` when nothing was added (including
an unknown talk id). A suggestion does not make the person busy. `POST /talks` for the same talk accepts it (it becomes
`confirmed`, source `conference`); `DELETE` dismisses it. Calling it again for the same person and talk
changes nothing. Tests and the gateway can replace the service with `app.dependency_overrides[get_service]`.

## Run locally

```
RAPPORT_WEB_DIR=web PYTHONPATH=src uv run python -m rapport_calendar
```

It listens on `0.0.0.0:8080`. Tests: `make test`, or `PYTHONPATH=src uv run pytest tests/calendar`.

## Privacy and telemetry

Spans (`calendar.view`, `calendar.agenda`, `calendar.propose`, `calendar.respond`) carry only the persona id and a
result count. Logs carry IDs and error class names only. Titles, notes, locations and search queries are never
logged or put on spans. The standalone server sets the `httpx` logger to WARNING because its INFO lines contain
full URLs, which include the agenda query.
