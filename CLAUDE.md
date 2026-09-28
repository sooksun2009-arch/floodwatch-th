# FloodWatch TH — working rules

People open this app to decide whether to drive into water. Every rule below
exists because it was broken here first, on this codebase, with the cost
written next to it.

---

## 1. Read the error before explaining it

Twice in one day a theory was built on a failure message that said nothing,
when the real message was one request away.

- `ConnectError: ` (empty) from the Bangkok gauge sync became "the site
  geo-blocks foreign addresses". It does not — a reader service outside
  Thailand fetched the same URL fine. An hour went into the wrong problem.
- `403 API key is invalid or rate limit exceeded` from Longdo became "the free
  plan excludes these services". It does not — the plan includes 100,000 of
  them a month. One sequential probe of each endpoint answered it in a minute:
  the key is entitled to some endpoints and not others.

**Rule.** When something external fails, the next action is to obtain its
actual words. Not a hypothesis, not a fix for the most likely cause. If the
words are not reachable, making them reachable is the task.

A third case, later the same day, was not an error message at all. The
satellite check kept finding nothing, and no log said why, because nothing had
failed. Fetching one tile over Ayutthaya and counting its pixels answered it in
a minute: 41,178 coloured pixels in the picture, alpha 0 at the point being
read. **When there is no error to read, measure the thing itself.**

**Corollaries the code now enforces:**
- Every failure path records *why*, not *that*: `describe_connection_failure`
  in `bma_stations.py`, `describe_failure` in `rain.py`.
- Those reasons are reachable over HTTP — `/api/stations/summary` carries
  `sources`, `/api/rain/status` carries `last_failure` — because a log line
  inside a container is invisible from here, and that invisibility is what
  made guessing feel reasonable.
- A success clears its recorded failure. An uncleared one reads as current
  and sent the Longdo diagnosis the wrong way a second time.
- Redact the key before returning upstream text; error bodies quote request
  URLs back.

---

## 2. Empty and broken must never look the same

The single most repeated fault in this project.

| What looked fine | What was true |
|---|---|
| 176 backend tests green, basemap drawn | Map rendered zero pins — the maplibre worker 404'd after bundling |
| Site answered HTTP 200 | Database was empty; the boot sync had never finished |
| Station reading displayed as current | It was 12 hours old; a naive Bangkok timestamp read back as UTC |
| Radar layer showing nothing | Correct — no rain. Indistinguishable from a dead feed |
| Camera list empty | Also correct — upstream returns only cameras with rain on them |

**The satellite layer took six rounds of this in one day.** Each round had a
different cause and every one looked identical from outside — a route check
that mentioned no flooding, on a day when a third of the central plain was
under water:

| What was actually wrong | How it looked |
|---|---|
| Asked "is the route *inside* an outline", and the outlines are 20 m across | no flooding |
| Got the first page only — 10 features for the country, the OGC default | no flooding |
| 12 MB ceiling against a 14 MB feed | no flooding |
| Asked for a page size the feed refuses, with no stated maximum | no flooding |
| The page we did get covered only the north; Bangkok and Ayutthaya were not in it | no flooding |
| Tiles are 512px and the pixel lookup assumed 256, reading the top-left quarter | no flooding |

What ended it was not better guessing. It was making the app able to say which:
`/api/flood-extent/status` reports `rings_loaded` (null = never fetched, 0 = the
country is dry), `coverage` gives the bounding box of what is in hand, and
`/near` answers how many outlines sit beside a point. Rounds five and six each
fell to one reading of those numbers.

The sixth was found by a screenshot from the user showing blue across Ayutthaya
while the API insisted there was nothing. **When the screen and the data
disagree, the screen is the evidence.**

**Rule.** Any display that can be legitimately empty must say which it is.
Pass through the denominator (`scanned`, `total`), the timestamp, or an
explicit reason. "Nothing to show" is a claim, and it needs evidence.

---

## 3. A cache is not a rate limit

The radar tile proxy had a per-tile cache and no budget. A cache stops the
*same* tile being fetched twice; a map being panned asks for a different tile
every time. It emptied the whole API key's daily allowance and took the
forecast and the camera list down with it — three features, one of them the
reason the key existed.

**Rule.** Any new call to a metered third party states its budget before it is
written. Separate budgets per kind of call, so the cheap high-volume thing
cannot starve the one someone is waiting on. Refuse over budget locally: a
request refused here costs nothing and cannot deepen the limit that caused it.

**A budget low enough to break normal use is not protecting anything; it is a
bug with a good excuse.** The satellite tile budget was set to 20 a minute, then
60, and both times production reported the minute exhausted with barely 3% of
the day spent — one screenful, then a blank layer. Size the per-minute figure
from what one screen actually requests, which with a retina viewport and the
map's tile buffer is far more than the arithmetic suggests, and let the daily
figure be the real guard.

Reduce volume at the source too — the radar stops requesting new tiles past
zoom 9 because its own resolution is about a kilometre, and each zoom level
past that asks for four times as many.

---

## 4. Optional things never shout over the point

A failed radar tile put a red banner across the flood map. The radar is
context someone switched on; the flood data is why the page exists.

**Rule.** Decoration fails silently. An unavailable tile is a transparent PNG,
not a 503. Errors from sources marked optional are dropped by source id, not by
guessing which words the message will contain — the guard matched
`tile|fetch|abort|network` and the message said `AJAXError: (503): …`.

Diagnostics still record it. Silent to the visitor, not silent to the operator.

---

## 5. Check the composed screen, not the component

Buttons collided twice: the radar toggle onto the map's zoom controls, and
"แจ้งน้ำท่วม" onto the chat button. Each was correctly placed in isolation.

A tall portrait photo pushed the vote buttons off the bottom of the popup —
they shipped and were unreachable on exactly the reports most worth voting on.

**Rule.** `frontend/smoke.cjs` measures the rendered page in a real browser at
1400×900: every floating control's rectangle, the popup image's height, whether
a button's bottom edge is inside the viewport. Add to it when adding chrome.

---

## 6. Write in the reader's words, not the data model's

"ขณะนี้ฝนตกที่กล้อง 95 จุด จาก 257 จุดทั่วประเทศ" only parses if you already
know the source is traffic cameras checked against radar. A reader asked what
it meant, which was the right question.

**Rule.** Say what the number means; put why it is believable in the small
print. Thai UI copy throughout. And per `frontend-design`: middle-dot meta
strings (`A · B · C`), ALL-CAPS labels, and a `→` glued to link text are
defaults rather than choices — this app already leans on the first one.

---

## 7. Rain is not flooding, a canal is not a road

The app's oldest rule and the reason it can be trusted. A gauge over its bank
is a measured fact about a canal. Heavy rain is a reason to expect trouble.
Neither is evidence that a particular road is impassable, and roads drain at
wildly different rates.

Each stays its own layer with its own sentence. Never converted into a flood
report, never folded into the verdict.

---

## 8. Safety asymmetries decide the defaults

- A wrong flood pin costs a detour; a real one held in a moderation queue can
  send someone into water they cannot see the depth of. The code therefore
  defaults to letting a corroborated or photographed report go live unreviewed.
  This deployment has both switched off since 2026-09-28, chosen once Telegram
  alerts made the queue visible within minutes rather than at dawn — the
  asymmetry argues for publishing only while nobody is watching the queue.
- Taking a hazard *off* the map needs more agreement than putting one on —
  three disputes, unchanged.
- Showing stale data as current is worse than showing nothing. Reports expire
  in 12 hours; gauges are flagged stale after 6.

---

## 9. Tests

- **Prove the test fails without the fix.** The overlap check was verified by
  removing `lg:bottom-24` and watching it report the exact collision.
- **No hardcoded dates.** `test_stations.py` began failing one morning with no
  code change — a fixture pinned to yesterday. Relative timestamps only.
- **Assert the instant, not the label.** Three tests checked
  `utcoffset() == +07:00`, which was true all the way through the bug that
  made a 12-hour-old reading read as current.
- **Run the frontend smoke test against the production build**, not only dev.
  `optimizeDeps` fixed dev while production stayed broken.
- Every suite is a plain script: `cd backend && .venv/Scripts/python.exe
  test_*.py`. Thai check names. ~420 backend checks, ~24 in the browser.

---

## 10. Before building

From the `brainstorming` skill, adapted to how this project actually runs:

Classify the work and say so. A **spike** answers a question and its output is
the answer. **Bounded** changes a flow that already exists here. **Architectural**
adds a subsystem or a new external dependency.

This user moves fast and says "ทำเลย" — that is genuine approval to implement,
not approval to skip thinking. What it does not waive:

- A new external dependency gets its budget, its failure mode, and its off
  switch described in one short paragraph *before* the first line. The radar
  quota incident is exactly the paragraph that was never written.
- Every third-party integration ships behind an unset-by-default key, and with
  it unset the app must behave byte for byte as before.
- "Reaching for a label to skip work IS the doubt." If it feels too small to
  describe, describe it anyway — it takes two sentences.

---

## 11. Verify against what is running, not against what you pushed

Twice in one day a fix was declared working, and twice the check had run
against the previous build: the wait loop was watching for a field that the
*old* deploy already had, so it never waited at all.

**Rule.** Wait on the behaviour the change was supposed to produce, not on the
shape of the response. "Does this route now mention the satellite layer" is a
correct condition; "does /status have a coverage key" is not, because the build
before it had one too.

Render's free tier takes three to five minutes. That is long enough to finish
reading a test result and believe it.

---

## 12. Two languages, and the things that must stay in one

The interface is Thai and English. Three rules came out of building that:

- **A missing translation falls back silently.** An English key that does not
  exist renders the Thai, which reads as a bug in someone else's language and
  is invisible in testing. `frontend/smoke.cjs` switches to English, counts the
  Thai left on the page, and fails if there is more than a handful.
- **Nothing translates what a person wrote.** Report text, place names and
  reporter names stay in the language they were typed in, labelled. Machine
  translating "the water is deep by the petrol station, saloon cars stay out"
  for someone about to drive into it is worse than showing them Thai.
- **Thai is the default for everyone**, including browsers asking for English.
  Guessing from `navigator.languages` was the first version and it is wrong
  here: plenty of people in Thailand run their phone in English and would
  rather read a Thai flood map in Thai. "EN" in the header is legible whatever
  you read.

The assistant answers the four common questions in English and says so, in one
bracketed line, for everything else. Half a feature that admits it is half is
worth more than one that switches languages without explanation.

While wiring that up, `"bang na"` scored 0.7 against จังหวัดพังงา on letter
similarity and the assistant reported, with complete confidence, that there was
no flooding there — a province 700 km from the question. **A confident answer
about the wrong place is the worst thing this code can produce, worse than no
answer.** Latin input now has to clear a much higher bar, and romanised names
come from a short list that is right rather than a general transliterator that
is nearly right.

---

## Where things are

- `backend/app/` — FastAPI. `routing.py` is the A→B feature; `rain.py`,
  `stations.py`, `bma_stations.py`, `history.py` are data sources;
  `storage.py` decides where photos live and which photo URLs are ours.
- `frontend/src/` — React + MapLibre. `MapView.jsx` builds every layer and
  popup with DOM nodes and `textContent`, never HTML strings: place names and
  report text are attacker-controllable.
- `flood_extent.py` — GISTDA satellite flood extent. Tiles for the map layer
  *and* for deciding whether a route crosses water, because the GeoJSON cannot
  answer that (see rule 2). `chatbot_en.py` holds the English wording and the
  romanised place names.
- `frontend/src/i18n.jsx` — every string in both languages, plus `depthText`,
  which puts inches beside centimetres for English readers.
- `keepalive.gs` — Google Apps Script. Keeps the free instance awake, watches
  data freshness, and relays the Bangkok gauges the container cannot reach.
- Deployment: Render free + Neon Postgres + Supabase Storage. No persistent
  disk; `render.yaml` is the source of truth for environment variables.
