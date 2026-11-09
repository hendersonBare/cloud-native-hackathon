# web — the two-phone demo page

Owned by the `web` workstream (docs/workstreams/web.md). The gateway serves this folder at `/`.

Plain HTML, CSS and ES modules; no build step.

## Run it

```bash
python3 -m http.server 5180 --directory web
```

Open http://localhost:5180/. Mock mode is the default (both phones talk to each other through a
`BroadcastChannel`, no backend needed). Add `?live=1` to use the gateway (SPEC §7.1).

The Calendar tab and People's "Find a time" use the calendar API (`src/rapport_calendar`, mounted by the
gateway at `/api/calendar`). To try them live without a gateway, serve this folder from the calendar's
dev server and open one phone in live mode:

```bash
RAPPORT_WEB_DIR=web PYTHONPATH=src uv run python -m rapport_calendar
```

Then open http://localhost:8080/phone.html?persona=acme.ava#/calendar. In mock mode the same screens use
`app/calendar-mock.js`, an in-browser replica that loads the same seed (`mock/calendar-seed.json`, a
byte-identical copy of `src/rapport_calendar/data/seed.json`) and syncs the two phones over the bus.

## Layout

| Path | What |
|---|---|
| `index.html`, `stage.css`, `stage.js` | The stage: two iPhone frames (Ava left, Bo right) scaled to fit the window, plus the presenter bar (mock badge, Malicious responder, Reset demo, full screen). Light theme only, as in the design. The arrow at the right of the bar hides it; the tab at the top brings it back. |
| `phone.html` | The phone app. Each frame loads `phone.html?persona=<id>&mock=1`. Open it on its own to see one phone. |
| `app/app.css` | Design tokens (light) and shared components. |
| `app/ui.js` | `h()` and SVG/icon helpers. Text always goes in as text nodes. |
| `app/main.js` | Hash router (`#/home`, `#/profile`, `#/calendar`, `#/live`, `#/tag`, `#/memory`, `#/people`, `#/person`, `#/exchange`, `#/match`). |
| `app/bus.js` | Event bus between the two phones; the event contract is in its header. |
| `app/flow.js`, `app/api.js` | Cross-phone connect flow and the gateway client. |
| `app/live-events.js`, `app/screens/match-live.js` | Live mode only: briefs, deep dive, agent decision and error events from the gateway. |
| `swarm/` | The swarm panel between the phones (toggle in the presenter bar). `model.js` is a pure reducer over swarm events, `view.js`/`panel.js` render it, `driver.js` feeds it (live: `/api/stream?view=swarm`; mock: replays `swarm/demo-events.json` when an encounter starts). |
| `app/data.js` | Demo cast and per-persona content (all fictional). |
| `app/calendar-api.js`, `app/calendar-mock.js` | Calendar client: live calls `/api/calendar/*`; mock is an in-browser replica with the same rules. Screens call `calendarClient(ctx)` and never branch on the mode. |
| `app/time.js` | Times are stored as UTC and always shown in America/Denver with the zone label (e.g. `3:30 PM MST`). |
| `app/people-model.js` | People directory, suggestions, "met" and search filters (pure, unit-tested). |
| `mock/` | Mock-mode data: the calendar seed and the research deck (`contracts/demo-research.json`). |
| `app/screens/<name>.js` / `.css` | One module per screen, each exporting `render(ctx)`. |

## Demo keys

- Home deck: drag the card, use the ✕ / ✓ buttons, or focus the card and press ← / →.
- Presenter: tick **Malicious responder** before Bo accepts to show the blocked prompt injection.
- Calendar: pick a day in the week strip; **+** adds an event, **Agenda** adds a talk, Accept / Decline answers a meeting your agents proposed.
- People: search or filter, open a person, then **Find a time** books coffee in the first slot free for both of you (free/busy only crosses companies).
