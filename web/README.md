# web — the two-phone demo page

Owned by the `web` workstream (docs/workstreams/web.md). The gateway serves this folder at `/`.

Plain HTML, CSS and ES modules; no build step.

## Run it

```bash
python3 -m http.server 5180 --directory web
```

Open http://localhost:5180/. There is one mode, and every feature works in it:

- **With a gateway** (the deployed page, or this folder served by `rapport_gateway`): the phones use it
  (SPEC §7.1). The stage checks `GET /healthz` once on load and tells both phones.
- **Without one** (a plain static server like the command above): everything runs in the browser and the
  two phones talk to each other through a `BroadcastChannel`. A right swipe on Bo replays the gateway's
  deep dive, decision and connect request from `swarm/demo-events.json`.
- **A gateway without a feature's API** (e.g. no `/api/calendar` or `/api/venue` mounted): that feature
  switches to its in-browser version on the first call (`app/mode.js`), without an error.

No badge, switch or URL flag. The logic is in `app/mode.js`.

The Calendar tab and People's "Find a time" use the calendar API (`src/rapport_calendar`, mounted by the
gateway at `/api/calendar`). To try them against the API without a gateway, serve this folder from the
calendar's dev server:

```bash
RAPPORT_WEB_DIR=web PYTHONPATH=src uv run python -m rapport_calendar
```

Then open http://localhost:8080/phone.html?persona=acme.ava#/calendar. Without the API the same screens use
`app/calendar-mock.js`, an in-browser replica that loads the same seed (`mock/calendar-seed.json`, a
byte-identical copy of `src/rapport_calendar/data/seed.json`) and syncs the two phones over the bus.

## Layout

| Path | What |
|---|---|
| `index.html`, `stage.css`, `stage.js` | The stage: two iPhone frames (Ava left, Bo right) scaled to fit the window, plus the presenter bar (Malicious responder, swarm panel, Reset demo, full screen). Light theme only, as in the design. The arrow at the right of the bar hides it; the tab at the top brings it back. |
| `phone.html` | The phone app. Each frame loads `phone.html?persona=<id>&mode=live\|mock` (the stage's one gateway check). Opened on its own it checks for itself. |
| `app/mode.js` | The single mode: `detectBackend()` (is there a gateway?) and `withFallback()` (a feature whose API is missing switches to its in-browser client). |
| `app/demo-script.js` | Without a gateway, the swipe steps (deep dive, decision, agent request) from the demo script. |
| `app/app.css` | Design tokens (light) and shared components. |
| `app/ui.js` | `h()` and SVG/icon helpers. Text always goes in as text nodes. |
| `app/main.js` | Hash router (`#/home`, `#/profile`, `#/calendar`, `#/live`, `#/tag`, `#/memory`, `#/people`, `#/person`, `#/exchange`, `#/match`). |
| `app/bus.js` | Event bus between the two phones; the event contract is in its header. |
| `app/flow.js`, `app/api.js` | Cross-phone connect flow and the gateway client. |
| `app/live-events.js`, `app/screens/match-live.js` | Briefs, deep dive, agent decision and error events, from the gateway or the demo script. |
| `swarm/` | The swarm panel between the phones (toggle in the presenter bar). `model.js` is a pure reducer over swarm events, `view.js`/`panel.js` render it, `driver.js` feeds it (live: `/api/stream?view=swarm`; mock: replays `swarm/demo-events.json` when an encounter starts). |
| `app/data.js` | Demo cast and per-persona content (all fictional). |
| `app/calendar-api.js`, `app/calendar-mock.js` | Calendar client: live calls `/api/calendar/*`; mock is an in-browser replica with the same rules. Screens call `calendarClient(ctx)` and never branch on the mode. |
| `app/time.js` | Times are stored as UTC and always shown in America/Denver with the zone label (e.g. `3:30 PM MST`). |
| `app/people-model.js` | People directory, suggestions, "met" and search filters (pure, unit-tested). |
| `app/venue-api.js`, `app/venue-mock.js`, `app/venue-model.js` | Venue map and directions: live calls `/api/venue/*` (`src/rapport_venue`); mock applies the same rules in the browser. `venue-model.js` is the shared geometry (GPS to floor-plan metres, door-corridor-door routes), pure and unit-tested. Screens call `venueClient(ctx)`. |
| `mock/` | Mock-mode data: the calendar seed, the venue floor plan (`venue.json`, byte-identical to `src/rapport_venue/data/venue.json`) and the research decks: Ava's (`demo-research.json`, a copy of `contracts/demo-research.json`) and Bo's (`demo-research-bo.json`), picked per viewer by `app/mock-research.js`. |
| `app/screens/<name>.js` / `.css` | One module per screen, each exporting `render(ctx)`. |

## Demo keys

- Home deck: drag the card, use the ✕ / ✓ buttons, or focus the card and press ← / →. The direction button beside **Talk about** opens **Find**: the floor plan with a walking route to that person. The route starts at your phone's GPS when **Share my location** is on and you are inside the venue, otherwise at your check-in spot; a person who isn't sharing shows nothing.
- Presenter: tick **Malicious responder** before Bo accepts to show the blocked prompt injection.
- Calendar: pick a day in the week strip; **+** adds an event, **Agenda** adds a talk, Accept / Decline answers a meeting your agents proposed.
- People: search or filter, open a person, then **Find a time** books coffee in the first slot free for both of you (free/busy only crosses companies).
