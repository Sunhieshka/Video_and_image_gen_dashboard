# Video generation → database workflow

Submits BytePlus Ark (Seedance) video generation tasks, polls them to completion,
and stores **every response parameter in its own column** — with per-task cost.

Handles **video and image generation**, each with its own pricing model,
its own database tables and its own dashboard table. Ships with a **React +
Tailwind web UI** and a CLI.

Supports the whole Seedance range: **2.5**, **2.0**, **2.0 Fast** and **2.0 Mini**.
Each has different capabilities, so unsupported combinations are refused before
the API call rather than failing mid-batch.


## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env    # fill in ARK_API_KEY
export ARK_API_KEY=...
python -m videogen init
```

Or `make install && make test`. The CLI reads `.env` automatically (real
environment variables take precedence), so `export ARK_API_KEY=...` is only
needed if you skip the file. Developed against Python 3.12; the code uses
`from __future__ import annotations` throughout so it also runs on 3.9.

**A note on the SDK dependency.** The Ark runtime is the `byteplussdkarkruntime`
*module* inside the `byteplus-python-sdk-v2` distribution — there is no PyPI
package by that name. Its `[ark]` extra declares only `cryptography`, but the
runtime also imports `httpx` and `sniffio` (recent `anyio` no longer pulls the
latter in), so both are listed explicitly in `requirements.txt`. Without them
the import fails at `ModuleNotFoundError`. The versions this was verified
against are noted at the bottom of `requirements.txt`.

## Web UI

```bash
./run.sh
```

Then open **http://localhost:8000**. The script creates the venv, installs UI
dependencies and builds the frontend on first run, then serves the API and the
built UI from one port. `make run` does the same.

**Generate** — prompt, model, resolution, aspect ratio and duration, plus
reference **images, video and audio**, each with its own upload box. Click a box
to pick files from your computer, or drag them in (or paste a URL below). Each
box filters the file picker to its own kind, and a file always lands in the box
matching what it actually is — drop a video on the Images box and it appears
under Videos. Uploads are stored by the backend, and the length of an uploaded
video is measured with `ffprobe` to price the video-input surcharge
automatically. The resolution list follows the
selected model (Fast and Mini stop at 720p; only 2.0 offers 4K), and the
estimated price updates live as you change the settings.

**Parallel tasks** — the **+** button above the form opens another generation
tab. Each tab keeps its own prompt, references and settings, and they run at the
same time: submitting returns immediately and every in-flight task is polled in
the background, so you can queue several and switch between them. The header
shows how many are running.

> **Uploads and reachability.** Ark fetches reference media from the URL it is
> given, so it has to be reachable from the internet — a `localhost` URL will
> fail. Set `VIDEOGEN_PUBLIC_BASE_URL` to a tunnel or deployment origin to make
> uploaded files usable, or paste URLs that are already public.
> `GET /api/config` reports whether the URLs being handed out are reachable.

**Video / Image** — a toggle above the form switches the tab between video and
image generation. Image generation is synchronous, so the result comes straight
back; prompt, model, size, output format, seed and watermark, plus input images for
image-to-image. The size options follow the model (pro is 1K/1.5K/2K; 5.0 and
4.5 are 2K/4K).

**Dashboard** (button, top right) — **Videos** and **Images** tabs, each its own
table with its own totals. Videos show tokens and token-based price; images show
a preview, the produced dimensions, per-image rate and price. Every generation in one table with total
cost, token usage and success/failure counts. Filter by status, model,
resolution, or free-text prompt search; **the totals recalculate for the active
filter**, so you can ask "what have I spent on 1080p"
directly. Click any row for the full detail: video, every stored parameter,
reference media, the poll-by-poll timeline and the raw API response.

For development with hot reload, run the API and Vite separately:

```bash
make dev        # API on :8000, UI on :5173
```

Open **http://localhost:5173** in that mode. Vite proxies `/api` and `/files`
through to the backend, so the same relative paths work in both modes. Note
Vite binds IPv6-only, so use `localhost`, not `127.0.0.1`. To point the proxy
at a different backend port, `API_PORT=8010 npm run dev`.

## Use

```bash
# see what each model supports and costs
python -m videogen models

# submit + poll + store, and save the file locally
python -m videogen run "a cat surfing at sunset" --duration 5 --ratio 16:9

# pick a model by alias: 2.5 | 2.0 | fast | mini
python -m videogen run "a cat surfing" --model mini --resolution 480p
python -m videogen run "a cat surfing" --model 2.0 --resolution 4k

# fire-and-forget, then collect later (good for batches)
python -m videogen submit "@prompt.txt" --image https://.../ref.png --video https://.../clip.mp4
python -m videogen sync          # refreshes every unfinished task once

python -m videogen list --status succeeded
python -m videogen show cgt-2025xxxx
python -m videogen export tasks.csv

# cost
python -m videogen price --resolution 1080p --duration 15 --input-video-seconds 24
python -m videogen price --compare --resolution 720p   # every model
python -m videogen cost --by total       # or --by day / --by model
python -m videogen recost                # after editing the price table
```

From Python:

```python
from videogen import db, workflow

conn = db.connect()
db.init_db(conn)

row = workflow.run(
    conn,
    "a cat surfing at sunset",
    model="dreamina-seedance-2-5-260628",
    references=[{"type": "image_url", "url": "https://.../ref.png"}],
    ratio="16:9", duration=15, resolution="1080p", generate_audio=True,
    input_video_seconds=24,   # total length of the reference videos

    output_format="mov", omni_reference_task_type="reference",
    download_dir="videos",
)
print(row["video_url"], row["total_tokens"], row["estimated_cost_usd"])
```

`examples/cookie_ad.py` is the original 7-reference cookie ad, wired through this workflow.

## Schema

**`video_tasks`** — one row per task, one column per parameter:

| group | columns |
|---|---|
| identity | `id`, `model`, `status` |
| content | `video_url`, `file_url`, `last_frame_url` |
| usage | `completion_tokens`, `total_tokens` |
| generation params | `seed`, `resolution`, `ratio`, `duration`, `framespersecond`, `frames`, `generate_audio`, `service_tier`, `execution_expires_after`, `draft`, `draft_task_id`, `priority`, `fileformat`, `output_format`, `subdivisionlevel`, `revised_prompt`, `safety_identifier` |
| error | `error_code`, `error_message` |
| cost | `estimated_cost_usd`, `unit_price_per_million_usd`, `cost_basis`, `cost_is_estimate`, `cost_currency`, `pricing_version`, `cost_note`, `input_video_seconds`, `has_video_input` |
| API timestamps | `created_at`, `updated_at` |
| request side | `prompt`, `requested_output_format`, `omni_reference_task_type`, `requested_ratio`, `requested_duration`, `requested_resolution`, `requested_generate_audio`, `request_payload` |
| bookkeeping | `submitted_at`, `last_polled_at`, `completed_at`, `poll_count`, `local_path`, `raw_response` |

**`task_references`** — reference images/videos (0..N per task, so a child table
rather than `ref1_url`, `ref2_url`, …): `task_id`, `position`, `ref_type`, `role`, `url`.

**`task_events`** — append-only status transitions: `task_id`, `observed_at`, `status`, `detail`.

**`v_video_tasks`** — flat view for dashboards; adds `generation_seconds` and
human-readable UTC timestamps.

**Uploads** live in `uploads/` (override with `VIDEOGEN_UPLOAD_DIR`), named by
content hash so the same file uploaded twice is stored once. The limit is 256MB
per file (`VIDEOGEN_MAX_UPLOAD_MB`).

**`v_spend_by_day`** / **`v_spend_total`** — cost rollups by day+model+resolution
and overall, each reporting how many rows used interpolated pricing.

### Design notes

- **Nested fields are hoisted.** `content.video_url` → `video_url`,
  `usage.total_tokens` → `total_tokens`, `error.code` → `error_code`.
- **Columns match the SDK's own response model.** The column list was checked
  against `ContentGenerationTask` in the installed SDK, which declares more
  than the docs' sample response shows — `frames`, `fileformat`, `output_format`,
  `subdivisionlevel`, `revised_prompt`, `draft_task_id`, `safety_identifier`,
  and `content.file_url` / `content.last_frame_url`. A test asserts every
  declared field has a column, so this cannot drift silently.
  Note `output_format` holds what the **API reported**; what you asked for is in
  `requested_output_format`.
- **New API fields become new columns automatically.** `db.ensure_columns` ALTERs
  the table for any response key it has not seen. Additive only — nothing is
  dropped or retyped. `raw_response` keeps the full payload as a backstop.
- **Upserts never erase data.** Each poll does
  `ON CONFLICT(id) DO UPDATE SET col = COALESCE(excluded.col, col)`, so a later
  response that omits a field cannot null out what an earlier one recorded.
- **Every poll is recorded**, so you can chart queue time vs. generation time.
- **Videos URLs expire.** `--download-dir` / `videogen download` pulls the file
  down and records `local_path`.

## Models

| family | aliases | resolutions | video input | omni reference |
|---|---|---|---|---|
| `seedance-2.5` | `2.5` | 480p, 720p, 1080p | up to 30s | yes |
| `seedance-2.0` | `2.0` | 480p, 720p, 1080p, **4K** | up to 15s | unverified |
| `seedance-2.0-fast` | `fast` | 480p, 720p | up to 15s | unverified |
| `seedance-2.0-mini` | `mini` | 480p, 720p | up to 15s | unverified |

`--model` takes an alias or a full model id; anything unrecognised is passed
through untouched, so a newly released model still works without a code change
(it just won't be costed or validated).

**Model ids are dated** (`dreamina-seedance-2-5-260628`). Only the 2.5 and 2.0
ids appear in the docs I was given, so the Fast and Mini aliases need their id
supplied once:

```bash
export ARK_MODEL_SEEDANCE_2_0_FAST=dreamina-seedance-2-0-fast-XXXXXX
export ARK_MODEL_SEEDANCE_2_0_MINI=dreamina-seedance-2-0-mini-XXXXXX
```

Without that, `--model mini` fails with a message telling you what to set rather
than guessing an id. Pricing still works by family, so `price --compare` quotes
all four regardless.

**Pre-flight validation.** `submit` checks the request against the model before
spending anything — `--model fast --resolution 1080p` fails immediately, as does
4K on anything but 2.0. Things that are merely suspicious warn instead: video
input past a model's priced ceiling, `omni_reference_task_type` on a 2.0 model
(documented only for 2.5), or multi-video reference off 2.5. Use `--no-strict`
to downgrade errors to warnings if BytePlus adds support before this table
catches up.

## Cost

Ark bills by token usage:

```
Estimated Price (USD) = Unit Price / 1,000,000 x Token Usage
```

Unit prices, USD per million tokens, as **no video input / with video input**
(video input takes a lower rate because it inflates the token count):

| model | 480p & 720p | 1080p | 4K |
|---|---|---|---|
| Seedance 2.5 | 10.70 / 6.40 | 11.70 / 7.00 | — |
| Seedance 2.0 | 7.00 / 4.30 | 7.70 / 4.70 | 4.00 / 2.40 |
| Seedance 2.0 Fast | 5.60 / 3.30 | — | — |
| Seedance 2.0 Mini | 3.50 / 2.10 | — | — |

**Token usage is only known once a task finishes**, so pricing works in two
stages:

1. **Before and during generation** — projected from the published per-video
   table, flagged `cost_is_estimate = 1` and shown with a `~` prefix.
2. **Once the API reports `total_tokens`** — the exact billed price via the
   formula above, `cost_is_estimate = 0`, with `cost_basis` set to
   `token_usage` or `token_usage_with_video` and the rate stored in
   `unit_price_per_million_usd`.

The two agree closely: 720p/5s with no video input is 108,900 tokens, giving
`10.70 / 1e6 x 108,900 = $1.1652` against the table's `$1.1560` — 0.8% apart, and
that same 0.8% holds across 480p, 720p and 1080p, which is what you would expect
from rounding in the published table.

Prices live in [`videogen/pricing.py`](videogen/pricing.py) and are stamped onto
each row as `pricing_version`, so a later change does not silently rewrite
history. `videogen recost` reprices every stored task against the current
table.

All four families are priced. Unsupported combinations return no price with a
reason rather than a wrong number.

Query a price without calling Ark:

```bash
python -m videogen price --resolution 720p --tokens 108900     # exact
python -m videogen price --resolution 720p --duration 5        # projected
python -m videogen price --compare --resolution 720p           # every model
```

**The projection** (used before a task runs) comes from the published per-video
table and inherits its caveats: with video input, only the endpoints of a range
are published (2–4s and 30s of input for 2.5, 15s for the 2.0 series) and the
surcharge between them is not linear, so intermediate values are interpolated;
input beyond the priced maximum clamps and notes that the figure is a lower
bound. None of this affects the final price, which is always the token formula.

Two assumptions worth knowing about, both easy to change in `pricing.py`:

- **`failed` and `cancelled` tasks are costed at $0** (`cost_basis = not_billed_failed`).
  Verify against an invoice if partial failures turn out to be billable.
- **`input_video_seconds` is not auto-detected by default.** Pass it explicitly,
  or use `--probe-input` to measure the reference videos with `ffprobe` if it is
  installed. Without it the video-input surcharge is skipped and the cost is
  understated — which matters most for multi-reference jobs like the cookie ad,
  where 7 references push a 1080p/15s generation to roughly $15.56 versus $8.54
  with no video input.

Reconcile against your BytePlus invoice before trusting these for billing.
`raw_response` and `total_tokens` are retained, so `videogen recost` can reprice
the whole history if the rates change.

## HTTP API

`videogen.api` (FastAPI) backs the UI and is usable on its own:

| endpoint | purpose |
|---|---|
| `GET /api/models` | families, capabilities and prices, for the form |
| `POST /api/price` | cost quote for a config, without calling Ark |
| `POST /api/generate` | submit a task; returns its id immediately |
| `GET /api/tasks` | filtered list + totals for that same filter (`status`, `model`, `resolution`, `search`, `estimated_only`) |
| `GET /api/tasks/{id}` | one task with references and timeline |
| `GET /api/stats` | overall spend and per-day rollup |
| `GET /api/image-models` | image models, tiers and per-image rates |
| `POST /api/images/price` | image cost quote |
| `POST /api/images/generate` | generate images (synchronous) |
| `GET /api/images` | filtered image list + totals |
| `GET /api/images/{id}` | one image request with its outputs and inputs |
| `POST /api/upload` | store reference images/video/audio, returns URLs |
| `GET /files/{name}` | serve an uploaded file |
| `GET /api/config` | upload limit and whether URLs are publicly reachable |

Generation is asynchronous: `POST /api/generate` returns as soon as the task is
created, and a background poller keeps the database current, so the browser only
has to read. That is what makes parallel tasks work — several can be in flight
at once.

**Errors carry their reason.** An unsupported model/resolution combination is a
`400`; a missing `ARK_API_KEY` is a `503`. Errors from Ark itself are translated
rather than swallowed, so the message and request id reach the UI:

| Ark says | you get | example |
|---|---|---|
| 401 / 403 | `503` | *Ark rejected the request (AuthenticationError): The API key status is not active.* |
| 429 | `429` | rate limited, retry shortly |
| 400 / 404 / 422 | `400` | the request we built was wrong |
| 5xx or unreachable | `502` | Ark is down or the network failed |

## Image pricing

Images are priced **per image**, not per token:

```
price = output_rate(model, pixels) x generated_images
      + input_rate(model) x billable_input_images
```

| model id | sizes | ≤ 2.61M px (1.5K or lower) | > 2.61M px | input images |
|---|---|---|---|---|
| `dola-seedream-5-0-pro-260628` | 1K, 1.5K, 2K | $0.045 | $0.09 | 1st free, then $0.003 each |
| `seedream-5-0-260128` | 2K, 4K | $0.035 | $0.035 | free |
| `seedream-4-5-251128` | 2K, 4K | $0.04 | $0.04 | free |

**The models take different size sets**, so the size list in the UI follows the
selected model and switching model snaps an invalid size to a supported one.
`images.generate()` refuses an unsupported pairing before spending anything
(`strict=False` downgrades it to a warning). An explicit `WxH` is passed through
unchecked.

Only **pro** is tiered, and it is the only model whose sizes straddle the
boundary: 1K (1.05M px) and 1.5K (2.36M px) are the $0.045 tier, while 2K comes
back as `1760x2368` — 4.17M px — and so costs $0.09. The tier is decided by the
pixels the API actually returned, not by the preset asked for; the presets are
mapped to representative pixel counts so a quote made beforehand lands on the
right side. 5.0 and 4.5 are flat rates, so their 2K/4K choice does not change
the price.

Seedream 5.0 Flash is not included. A flash model id is reported as unknown and
left uncosted rather than being priced at the base 5.0 rate, which would be
wrong.

**Layer decomposition is deliberately not priced.** It is a separate rate card
and this project does not use it. A request that asks for it is flagged in
`cost_note` rather than being silently costed at the single-image rate.

```bash
python -m videogen image-price --size 1.5K --images 2 --inputs 3
python -m videogen image-price --compare --size 1K
python -m videogen image "a sculptural hat portrait" --size 2K --download-dir images
python -m videogen images
```

### Image tables

Images get their own tables rather than sharing `video_tasks`: the API is
synchronous, the pricing model is per-image rather than per-token, and one
request returns N images.

**`image_tasks`** — one row per request: `model`, `prompt`, `size`,
`output_format`, `response_format`, `watermark`, `seed`, `guidance_scale`,
`generated_images`, `input_images`, `output_tokens`, `total_tokens`,
`estimated_cost_usd`, `output_rate_usd`, `output_cost_usd`, `input_cost_usd`,
`latency_ms`, `error_code`, `error_message`, `raw_response`.

**`image_outputs`** — one row per produced image: `url`, `size`, `width`,
`height`, `pixels`, `rate_usd`, `local_path`.

**`image_inputs`** — input images, with `billable` recording which ones were
charged (the first is free on pro).

**`v_image_tasks`** / **`v_image_spend_total`** — flat view and spend rollup.

## Inspecting the database

`videogen list`, `show` and `cost` cover the common cases. For ad-hoc queries the
file is plain SQLite:

```bash
sqlite3 videogen.db ".tables"            # video_tasks, task_references, task_events + views
sqlite3 videogen.db ".schema video_tasks"
```

The `v_video_tasks` view is the readable one — the raw table has ~50 columns:

```bash
sqlite3 -header -column videogen.db \
  "SELECT id, status, resolution, duration, total_tokens, estimated_cost_usd FROM v_video_tasks;"
```

`.mode line` prints one field per row, which is the sane way to read a single
task in full:

```bash
sqlite3 videogen.db ".mode line" "SELECT * FROM video_tasks WHERE id='cgt-...';"
```

Useful queries:

```bash
# spend per day
sqlite3 -header -column videogen.db "SELECT * FROM v_spend_by_day;"

# what failed, and why
sqlite3 -header -column videogen.db \
  "SELECT id, error_code, error_message FROM video_tasks WHERE status='failed';"

# reference media for a task
sqlite3 -header -column videogen.db \
  "SELECT position, ref_type, role, url FROM task_references WHERE task_id='cgt-...';"

# how long each task took, queue to finish
sqlite3 -header -column videogen.db \
  "SELECT task_id, status, observed_at FROM task_events ORDER BY event_id;"
```

An interactive session (`.quit` to exit), or a GUI:

```bash
sqlite3 videogen.db
```

Any SQLite browser works — DB Browser for SQLite, TablePlus, or the SQLite
extension in VS Code — just open `videogen.db`.

## Batch + scheduled collection

`submit` returns immediately, so you can queue many jobs and let a cron job
collect them:

```bash
*/2 * * * * cd /path/to/dashboard && python -m videogen sync >> sync.log 2>&1
```

`sync` is idempotent and skips terminal tasks; a single failing task logs to
`task_events` and does not stop the sweep.

## Tests

```bash
python tests/test_workflow.py
```

```bash
python tests/run_all.py
```

`test_workflow.py` runs the full submit → poll → persist path against a fake SDK
(`tests/fake_ark.py`), covering success, failure, unknown-field auto-columning,
reference storage, event logging, sync idempotency, cost persistence, recosting,
CSV export, and a matrix running all four model families end to end.
`test_pricing.py` asserts the price table reproduces **every** published figure
exactly, plus interpolation bounds, clamping, unsupported combinations and
monotonicity. `test_models.py` covers alias resolution, capability lookup and
validation. `test_real_sdk.py` runs the flattener and the schema against the
**real** SDK's pydantic response model and asserts no declared field is
unmodelled; it skips cleanly if the SDK is not installed. None need an API key
or network.

## Connecting to a different database

### Choosing the SQLite file

The default is a file called `videogen.db` in the working directory. Point it
anywhere, three ways — the CLI flag wins, then the environment, then the default:

```bash
python -m videogen --db /data/prod.db list     # per command
export VIDEOGEN_DB=/data/prod.db               # per shell, also used by the API
VIDEOGEN_DB=/data/staging.db ./run.sh          # per run
```

`.env` is read automatically, so `VIDEOGEN_DB=...` there is picked up by both the
CLI and the server. Separate files are the simplest way to keep environments
apart:

```bash
VIDEOGEN_DB=dev.db ./run.sh        # scratch work
VIDEOGEN_DB=prod.db ./run.sh       # real spend
```

`db.connect(":memory:")` gives a throwaway database, which is what the tests use.

### What SQLite gives you here, and where it stops

The schema is created with `CREATE TABLE IF NOT EXISTS`, so pointing at a new
file just works; `init_db()` runs on every command and is idempotent. Foreign
keys are enabled per connection and the journal is set to WAL, so the API's
background poller can write while the UI reads.

The limits worth knowing before you outgrow it:

- **One writer at a time.** WAL allows concurrent readers, but a second writer
  blocks. Fine for one server polling a handful of tasks; not fine for several
  processes writing at once.
- **The file must be on local disk.** SQLite over NFS or a network share
  corrupts.
- **No network access.** Every process needs the file, so you cannot put the UI
  on one host and the database on another.

If you hit any of those, move to a client/server database.

### Porting to Postgres (or MySQL)

Everything is plain SQL over DB-API, so the port is mechanical rather than a
rewrite. SQL lives in five files: `videogen/db.py` (16 statements),
`videogen/api.py` (15), `videogen/images.py` (10), `videogen/cli.py` and
`videogen/workflow.py` (3 each), plus `videogen/schema.sql`.

**1. The connection.** `db.connect()` is the only place `sqlite3` is opened.
Swap it for `psycopg.connect()`, and return a connection whose `.execute()`
yields dict-like rows — `psycopg.rows.dict_row` — so the callers that index rows
by name keep working:

```python
import psycopg
from psycopg.rows import dict_row

def connect(dsn=os.environ["VIDEOGEN_DSN"], **_):
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
```

psycopg exposes `.execute()` on the *connection*, so most call sites are
unchanged. Two things are not: `conn.executescript()` in `init_db()` becomes a
single `conn.execute()` with the whole file, and `conn.executemany()` — used in
`db.replace_references()` and `images._store_outputs/_store_inputs` — only
exists on a cursor, so those three become `with conn.cursor() as cur:
cur.executemany(...)`.

**2. Placeholders.** SQLite uses `?`, Postgres and MySQL use `%s`. A
search-and-replace across those five files; there are no named parameters.

**3. Drop the PRAGMAs.** Postgres enforces foreign keys by default and has no
WAL setting to make. `columns()` reads `PRAGMA table_info(...)`; replace it with:

```sql
SELECT column_name FROM information_schema.columns WHERE table_name = %s
```

This matters more than it looks — `ensure_columns()` uses it to add a column
when the API returns a field the schema does not model.

**4. Types in `schema.sql`.** `INTEGER` → `BIGINT`, `REAL` → `DOUBLE PRECISION`,
`TEXT` stays. The `0/1` boolean columns can become `BOOLEAN`, or stay as
`SMALLINT` if you would rather not touch the code that writes `int(...)`.
`INTEGER PRIMARY KEY AUTOINCREMENT` on `task_events` becomes
`BIGINT GENERATED ALWAYS AS IDENTITY` (Postgres) or `AUTO_INCREMENT` (MySQL).

**5. Three SQLite-isms in the views:**

| SQLite | Postgres |
|---|---|
| `datetime(created_at, 'unixepoch')` | `to_timestamp(created_at)` |
| `date(created_at, 'unixepoch')` | `to_timestamp(created_at)::date` |
| `SUM(status = 'succeeded')` | `COUNT(*) FILTER (WHERE status = 'succeeded')` |

The last one is a real trap: SQLite treats a comparison as 0/1 and sums it,
while Postgres rejects summing a boolean. The same aggregate appears inline in
`api.py`'s totals queries, not only in `schema.sql`.

**6. Upserts need no change.** `INSERT … ON CONFLICT(id) DO UPDATE SET` is the
same in Postgres. MySQL needs `INSERT … ON DUPLICATE KEY UPDATE` instead, and
has no `COALESCE(excluded.col, col)` — use `VALUES(col)`.

**7. Concurrency.** `check_same_thread` is a SQLite concept; drop the argument.
Give the API a connection pool (`psycopg_pool.ConnectionPool`) instead of
opening one per request, and the one-writer limit disappears.

Nothing above touches pricing, the workflow, the API contract or the UI — those
only ever see rows.
