-- Video generation task store.
-- One row per Ark content-generation task; every scalar field the API returns
-- gets its own column. Variable-length inputs (reference images/videos) live in
-- task_references, and every observed status change lands in task_events.

CREATE TABLE IF NOT EXISTS video_tasks (
    -- identity
    id                        TEXT PRIMARY KEY,          -- cgt-...
    model                     TEXT,
    status                    TEXT,                      -- queued|running|succeeded|failed|cancelled

    -- content
    video_url                 TEXT,                      -- content.video_url
    file_url                  TEXT,                      -- content.file_url
    last_frame_url            TEXT,                      -- content.last_frame_url

    -- usage
    completion_tokens         INTEGER,                   -- usage.completion_tokens
    total_tokens              INTEGER,                   -- usage.total_tokens

    -- generation parameters echoed back by the API
    seed                      INTEGER,
    resolution                TEXT,
    ratio                     TEXT,
    duration                  INTEGER,
    framespersecond           INTEGER,
    generate_audio            INTEGER,                   -- 0/1
    service_tier              TEXT,
    execution_expires_after   INTEGER,
    draft                     INTEGER,                   -- 0/1
    draft_task_id             TEXT,
    priority                  INTEGER,
    frames                    INTEGER,                   -- total frames rendered
    fileformat                TEXT,                      -- container the API produced
    output_format             TEXT,                      -- as reported by the API
    subdivisionlevel          TEXT,
    revised_prompt            TEXT,                      -- prompt after API rewriting
    safety_identifier         TEXT,

    -- failure detail
    error_code                TEXT,                      -- error.code
    error_message             TEXT,                      -- error.message

    -- API timestamps (unix seconds)
    created_at                INTEGER,
    updated_at                INTEGER,

    -- request side (what we asked for)
    prompt                    TEXT,
    requested_output_format   TEXT,                      -- extra_body.output_format
    omni_reference_task_type  TEXT,                      -- extra_body.omni_reference_task_type
    requested_ratio           TEXT,
    requested_duration        INTEGER,
    requested_generate_audio  INTEGER,
    request_payload           TEXT,                      -- full request as JSON

    -- cost (see videogen/pricing.py)
    estimated_cost_usd        REAL,
    cost_basis                TEXT,                      -- how it was computed
    cost_is_estimate          INTEGER,                   -- 0 = exact table price
    cost_currency             TEXT,
    pricing_version           TEXT,
    cost_note                 TEXT,
    unit_price_per_million_usd REAL,                     -- token rate applied
    input_video_seconds       REAL,                      -- total reference-video input
    has_video_input           INTEGER,                   -- selects the token rate
    requested_resolution      TEXT,

    -- local bookkeeping
    submitted_at              TEXT,                      -- ISO8601 UTC
    last_polled_at            TEXT,
    completed_at              TEXT,
    poll_count                INTEGER NOT NULL DEFAULT 0,
    local_path                TEXT,                      -- downloaded file, if any
    raw_response              TEXT                       -- last full response as JSON
);

CREATE INDEX IF NOT EXISTS idx_video_tasks_status     ON video_tasks(status);
CREATE INDEX IF NOT EXISTS idx_video_tasks_created_at ON video_tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_video_tasks_model      ON video_tasks(model);

-- Reference images/videos are 0..N per task, so they get their own table
-- rather than ref1_url, ref2_url, ... columns.
CREATE TABLE IF NOT EXISTS task_references (
    task_id   TEXT    NOT NULL,
    position  INTEGER NOT NULL,   -- order in the content array
    ref_type  TEXT,               -- image_url | video_url
    role      TEXT,               -- reference_image | reference_video | first_frame | ...
    url       TEXT,
    PRIMARY KEY (task_id, position),
    FOREIGN KEY (task_id) REFERENCES video_tasks(id) ON DELETE CASCADE
);

-- Append-only log of what each poll saw. Useful for latency charts.
CREATE TABLE IF NOT EXISTS task_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    observed_at TEXT NOT NULL,     -- ISO8601 UTC
    status      TEXT,
    detail      TEXT,
    FOREIGN KEY (task_id) REFERENCES video_tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_events_task_id ON task_events(task_id);

-- Convenience view for a dashboard: one flat row with wall-clock duration.
CREATE VIEW IF NOT EXISTS v_video_tasks AS
SELECT
    id, model, status, resolution, ratio, duration, framespersecond,
    generate_audio, seed, service_tier, priority, draft,
    completion_tokens, total_tokens,
    estimated_cost_usd, cost_is_estimate, cost_basis, cost_note,
    unit_price_per_million_usd, has_video_input,
    input_video_seconds, pricing_version,
    (updated_at - created_at)                     AS generation_seconds,
    datetime(created_at, 'unixepoch')             AS created_at_utc,
    datetime(updated_at, 'unixepoch')             AS updated_at_utc,
    output_format, requested_output_format, revised_prompt,
    prompt, video_url, file_url, local_path,
    error_code, error_message, poll_count
FROM video_tasks;

-- Spend rollups for a dashboard.
CREATE VIEW IF NOT EXISTS v_spend_by_day AS
SELECT
    date(created_at, 'unixepoch')            AS day,
    model,
    resolution,
    COUNT(*)                                 AS tasks,
    SUM(status = 'succeeded')                AS succeeded,
    SUM(status = 'failed')                   AS failed,
    ROUND(SUM(COALESCE(estimated_cost_usd, 0)), 4) AS cost_usd,
    SUM(COALESCE(cost_is_estimate, 0))       AS estimated_rows,
    SUM(COALESCE(total_tokens, 0))           AS tokens
FROM video_tasks
GROUP BY day, model, resolution
ORDER BY day DESC, cost_usd DESC;

CREATE VIEW IF NOT EXISTS v_spend_total AS
SELECT
    COUNT(*)                                       AS tasks,
    ROUND(SUM(COALESCE(estimated_cost_usd, 0)), 4) AS cost_usd,
    ROUND(AVG(NULLIF(estimated_cost_usd, 0)), 4)   AS avg_cost_usd,
    SUM(COALESCE(cost_is_estimate, 0))             AS estimated_rows,
    SUM(COALESCE(total_tokens, 0))                 AS tokens
FROM video_tasks;

-- ---------------------------------------------------------------------------
-- Image generation. Kept in its own tables rather than sharing video_tasks:
-- the API is synchronous (no polling), priced per image rather than per token,
-- and returns N images per request.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS image_tasks (
    -- identity (the API returns no task id, so one is generated locally)
    id                     TEXT PRIMARY KEY,
    model                  TEXT,
    status                 TEXT,                  -- succeeded | failed

    -- request
    prompt                 TEXT,
    size                   TEXT,                  -- as requested, e.g. 2K
    output_format          TEXT,
    response_format        TEXT,                  -- url | b64_json
    watermark              INTEGER,
    seed                   INTEGER,
    guidance_scale         REAL,
    optimize_prompt        INTEGER,
    sequential_image_generation TEXT,
    layer_decomposition    INTEGER,
    request_payload        TEXT,                  -- JSON

    -- usage as reported by the API
    generated_images       INTEGER,
    input_images           INTEGER,
    output_tokens          INTEGER,
    total_tokens           INTEGER,

    -- cost (see videogen/image_pricing.py)
    estimated_cost_usd     REAL,
    output_rate_usd        REAL,                  -- per-image output rate used
    output_cost_usd        REAL,
    input_cost_usd         REAL,
    cost_basis             TEXT,
    cost_is_estimate       INTEGER,
    cost_currency          TEXT,
    pricing_version        TEXT,
    cost_note              TEXT,

    -- failure detail
    error_code             TEXT,
    error_message          TEXT,

    -- timestamps
    created                INTEGER,               -- unix seconds, from the API
    created_at             INTEGER,
    submitted_at           TEXT,                  -- ISO8601 UTC
    completed_at           TEXT,
    latency_ms             INTEGER,

    raw_response           TEXT                   -- full response as JSON
);

CREATE INDEX IF NOT EXISTS idx_image_tasks_status  ON image_tasks(status);
CREATE INDEX IF NOT EXISTS idx_image_tasks_model   ON image_tasks(model);
CREATE INDEX IF NOT EXISTS idx_image_tasks_created ON image_tasks(created);

-- One row per image produced; a request can return several.
CREATE TABLE IF NOT EXISTS image_outputs (
    task_id        TEXT NOT NULL,
    position       INTEGER NOT NULL,
    url            TEXT,
    size           TEXT,                          -- as produced, e.g. 1760x2368
    width          INTEGER,
    height         INTEGER,
    pixels         INTEGER,                       -- drives the tiered rate
    output_format  TEXT,
    rate_usd       REAL,                          -- rate applied to this image
    description    TEXT,
    name           TEXT,
    z_index        INTEGER,
    local_path     TEXT,
    PRIMARY KEY (task_id, position),
    FOREIGN KEY (task_id) REFERENCES image_tasks(id) ON DELETE CASCADE
);

-- Input (reference) images supplied with the request.
CREATE TABLE IF NOT EXISTS image_inputs (
    task_id   TEXT NOT NULL,
    position  INTEGER NOT NULL,
    url       TEXT,
    billable  INTEGER,                            -- first image is free on pro
    PRIMARY KEY (task_id, position),
    FOREIGN KEY (task_id) REFERENCES image_tasks(id) ON DELETE CASCADE
);

CREATE VIEW IF NOT EXISTS v_image_tasks AS
SELECT
    id, model, status, prompt,
    size, output_format, watermark, seed,
    generated_images, input_images, output_tokens, total_tokens,
    estimated_cost_usd, output_rate_usd, output_cost_usd, input_cost_usd,
    cost_is_estimate, cost_basis, cost_note, pricing_version,
    latency_ms,
    datetime(COALESCE(created, created_at), 'unixepoch') AS created_at_utc,
    error_code, error_message,
    (SELECT url  FROM image_outputs o WHERE o.task_id = image_tasks.id
      ORDER BY position LIMIT 1) AS first_url,
    (SELECT size FROM image_outputs o WHERE o.task_id = image_tasks.id
      ORDER BY position LIMIT 1) AS first_size
FROM image_tasks;

CREATE VIEW IF NOT EXISTS v_image_spend_total AS
SELECT
    COUNT(*)                                       AS tasks,
    COALESCE(SUM(generated_images), 0)             AS images,
    ROUND(SUM(COALESCE(estimated_cost_usd, 0)), 4) AS cost_usd,
    ROUND(AVG(NULLIF(estimated_cost_usd, 0)), 4)   AS avg_cost_usd,
    SUM(COALESCE(cost_is_estimate, 0))             AS estimated_rows,
    COALESCE(SUM(total_tokens), 0)                 AS tokens
FROM image_tasks;
