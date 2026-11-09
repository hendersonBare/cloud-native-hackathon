# rapport_venue

Find a person at the venue. The phone sends its GPS fix; the service places it on the floor plan (metres), keeps it
only while the person consents to be found, and answers with walking directions between two people: out of a room by
its door, along the concourse, into the other room by its door. It is a FastAPI `APIRouter` (prefix `/api/venue`)
that the gateway mounts in-process, plus a standalone dev server that serves the same router and, optionally, the
`web/` folder.

State is in memory (the gateway runs one replica) and starts from `data/venue.json`, which has a byte-identical copy
at `web/mock/venue.json` for the JS mock. `reset()` restores it.

## Endpoints

All under `/api/venue`. Errors are `{"detail": "<code>"}`; validation errors are FastAPI's 422.

| Method | Path | Body / query | Returns | Errors |
|---|---|---|---|---|
| GET | `` | `persona_id`; header `X-Venue-Token?` | `VenueView`: the public floor plan, my `sharing` flag, `me` (my `Position`: GPS only with my device's token, else my check-in spot) | 404 `unknown_persona` |
| PUT | `/location` | `LocationUpdate`: `persona_id`, `lat` (-90..90), `lng` (-180..180), `accuracy_m?` (0..5000), `sharing_token` | `Position` (`source: "gps"`) | 404 `unknown_persona`, 403 `not_this_device`, 409 `sharing_off`, 422 `too_inaccurate`, 422 `outside_venue` |
| PUT | `/sharing` | `SharingBody`: `persona_id`, `enabled` (a JSON boolean), `sharing_token?` | `SharingState` (with this device's `sharing_token` when turned on) | 404 `unknown_persona`, 403 `shared_from_another_device` |
| GET | `/directions` | `persona_id`, `to`; header `X-Venue-Token?` | `Directions` (the JSON key is `from`; my own GPS start only with my device's token) | 404 `unknown_persona`, 422 `same_person` |

The standalone app also serves `GET /healthz` -> `{"ok": true, "version": ...}`.

`Directions`: `persona_id`, `to_persona_id`, `peer_status` (`sharing` | `not_sharing`), `from` and `to` (`Position`),
`route` (waypoints `[x, y]`), `distance_m` (walking distance along the route), `bearing_deg` (straight-line, clockwise
from north), `compass` (`north`, `north-east`, ...) and `legs`. Legs carry only the fields of their kind:
`{"kind": "same_room" | "leave" | "enter", "room_id"}`, `{"kind": "walk", "room_id", "direction": "east" | "west",
"meters"}`, `{"kind": "arrive", "meters", "compass"}`.

Models are in `models.py`. They live here because `rapport_common` is integrator-owned: **CONTRACT CHANGE REQUEST**
to promote them into `rapport_common.models`.

## Rules in short

- Coordinates are floor-plan metres: origin at the south-west corner, x east, y north. `geometry.py` is an exact port
  of `web/app/venue-model.js` (same numbers, including `Math.round`'s ties-up rounding), so the find screen, the JS
  mock and the API agree. A fix is converted with an equirectangular projection from the anchor `geo`, clamped into
  the building and rounded to 0.1 m. More than `outside_margin_m` (15 m) outside it is 422 `outside_venue`.
- A fix with `accuracy_m` above `max_accuracy_m` (100 m) is 422 `too_inaccurate`. A fix without `accuracy_m` is
  accepted.
- Every person in `rapport_common.names.personas()` is known; anyone else is 404 `unknown_persona`.
- Sharing is a per-person consent flag, seeded from `venue.json` `sharing` (missing = off). Sending a fix while not
  sharing is 409 `sharing_off`. Turning sharing off deletes the stored fix at once; turning it on again does not
  bring it back.
- Where someone is: their stored GPS fix if they share and it is at most `gps_ttl_s` (600 s) old, else their
  check-in spot (`source: "checkin"`, no accuracy or time). Someone without a check-in spot is at the corridor's
  centre. Fixes older than `gps_ttl_s` are deleted, not just hidden.
- The room of a point is the first non-corridor room (file order) whose rectangle contains it, edges included; else
  the corridor.
- Directions to yourself are 422 `same_person`. You can find someone who shares even when you do not share yourself
  (sharing means "others may find me").

## Privacy

- Raw GPS is never stored or logged. Only the placed point (venue metres, 0.1 m), its accuracy and its time are
  kept, in memory, while the person shares and for at most `gps_ttl_s`. Latitude and longitude never go on a span or
  a log line, and no response contains them.
- Consent: nobody is placed by GPS unless their `sharing` flag is on, and turning it off deletes their fix.
- Per-device consent: turning sharing on returns a random `sharing_token` to that device only; the service keeps
  only its SHA-256. GPS fixes need the token (403 `not_this_device`), and so does turning sharing on again while a
  device holds it (403 `shared_from_another_device`), so nobody else can feed or take over someone's location.
  Turning sharing off never needs the token: it only reduces exposure, and it lets a person switch off sharing that
  someone else switched on. Demo reset forgets every token. The token is never logged or put on a span.
- My own GPS-placed position (`GET /api/venue` `me`, and `from` in directions) is returned only with my device's
  token in the `X-Venue-Token` header (a header, so it never lands in an access log); anyone else gets my check-in
  spot. A peer who shares is still placed by GPS in directions: that is what they consented to.
- What remains: the gateway has no logins, so anyone can still switch sharing on for a person who isn't sharing.
  That reveals only the person's check-in spot (no GPS), and anyone, including that person, can switch it off.
- `peer_status: "not_sharing"` reveals nothing about the peer: `to` is `null`, `route` and `legs` are empty and
  `distance_m`, `bearing_deg` and `compass` are `null`. The answer is the same whether or not they ever shared.
- `GET /api/venue` returns the public floor plan only: never other people's check-in spots, sharing flags or the GPS
  anchor.
- Spans `venue.view`, `venue.location`, `venue.sharing` and `venue.directions` carry only `rapport.persona_id`, plus
  `rapport.venue.peer_status` on directions. Logs carry persona ids and the sharing flag only.
- Request lines (access logs, the HTTP server span) carry only paths and persona ids: the GPS fix travels in the
  `PUT /location` body.
- `json.loads` accepts `NaN` and `Infinity`; `LocationUpdate` turns them into a 422 (FastAPI would otherwise fail
  with a 500 while echoing them back).

## Configuration

| Variable | Meaning |
|---|---|
| `RAPPORT_VENUE_ORIGIN` | `lat,lng` in degrees of the floor plan's south-west corner, replacing `geo` from `venue.json`, so the real building can be anchored on demo day. A malformed value is ignored with a warning that does not repeat it. |
| `RAPPORT_WEB_DIR` | Standalone only: serve this folder at `/` after the API routes. |
| `RAPPORT_VERSION` | Reported by `/healthz`. |

The floor plan, `gps_ttl_s`, `outside_margin_m`, `max_accuracy_m`, check-in spots and seed sharing flags come from
`data/venue.json`. The service checks at start-up that it has a corridor and that every other room has a door.

## Mounting in the gateway

```python
from rapport_venue import api as venue

app.include_router(venue.router)  # before the StaticFiles mount

# POST /api/demo/reset
venue.get_service().reset()
```

Both are wired in `src/rapport_gateway/app.py` and `src/rapport_gateway/routers/demo.py`. Tests and the gateway can
replace the service with `app.dependency_overrides[get_service]` (the demo reset calls the module singleton).

## Run locally

```
RAPPORT_WEB_DIR=web PYTHONPATH=src uv run python -m rapport_venue
```

It listens on `127.0.0.1:8080`; set `RAPPORT_VENUE_HOST=0.0.0.0` to reach it from another machine. Tests: `make test`, or `PYTHONPATH=src uv run pytest tests/venue`.

## Security review needed

This package handles location data. Please review:

- `src/rapport_venue/service.py`: consent flag, deleting fixes on opt-out and after `gps_ttl_s`, what
  `not_sharing` reveals, and that latitude and longitude are never stored, logged or put on spans.
- `src/rapport_venue/models.py`: `LocationUpdate` validation (ranges, NaN and Infinity, strict boolean consent).
- `src/rapport_venue/geometry.py` `public_venue`: what the client may see of the venue file.
- `src/rapport_gateway/routers/demo.py`: the demo reset also clears venue state.
