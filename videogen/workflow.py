"""Submit → poll → persist workflow for Ark video generation.

Every response the API returns is flattened and written straight into
video_tasks, one column per parameter. Nothing is lost: unmodelled fields get
new columns automatically and the full payload is kept in raw_response.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import client as ark
from . import db
from . import models
from . import pricing
from .flatten import extract_prompt, extract_references, flatten_task, is_terminal

POLL_INTERVAL_SECONDS = 10
POLL_TIMEOUT_SECONDS = 30 * 60


def submit(
    conn: sqlite3.Connection,
    prompt: str,
    *,
    model: str | None = None,
    references: Sequence[Mapping[str, Any]] = (),
    ratio: str = "16:9",
    duration: int = 5,
    resolution: str | None = None,
    generate_audio: bool = True,
    output_format: str | None = None,
    omni_reference_task_type: str | None = None,
    input_video_seconds: float | None = None,
    extra: Mapping[str, Any] | None = None,
    strict: bool = True,
    ark_client=None,
) -> str:
    """Create a task and write the pending row. Returns the task id."""
    model = models.resolve_model(model)

    # Fail before spending anything on a combination the model cannot do.
    errors, warnings = models.validate_request(
        model,
        resolution=resolution,
        duration=duration,
        input_video_seconds=input_video_seconds,
        omni_reference_task_type=omni_reference_task_type,
        reference_video_count=sum(
            1 for r in references
            if (r.get("type") or r.get("ref_type")) == "video_url"
        ),
    )
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors and strict:
        raise ValueError("; ".join(errors))
    for error in errors:
        print(f"warning (strict=False): {error}", file=sys.stderr)

    # Only now, once the request is known to be valid, do we need credentials.
    ark_client = ark_client or ark.make_client()
    content = ark.build_content(prompt, references)

    extra_body: dict[str, Any] = {}
    if omni_reference_task_type:
        extra_body["omni_reference_task_type"] = omni_reference_task_type
    if output_format:
        extra_body["output_format"] = output_format

    request: dict[str, Any] = {
        "model": model,
        "content": content,
        "generate_audio": generate_audio,
        "ratio": ratio,
        "duration": duration,
    }
    if resolution:
        request["resolution"] = resolution
    if extra_body:
        request["extra_body"] = extra_body
    if extra:
        request.update(extra)

    response = ark.create_task(ark_client, **request)
    row = flatten_task(response)
    task_id = row.get("id")
    if not task_id:
        raise RuntimeError(f"create returned no task id: {row}")

    row.update(
        {
            "prompt": extract_prompt(content),
            "requested_output_format": output_format,
            "omni_reference_task_type": omni_reference_task_type,
            "requested_ratio": ratio,
            "requested_duration": duration,
            "requested_generate_audio": int(generate_audio),
            "requested_resolution": resolution,
            "input_video_seconds": input_video_seconds,
            # Video input selects a different token rate, so record it whether
            # or not the caller measured the input length.
            "has_video_input": int(any(
                (r.get("type") or r.get("ref_type")) == "video_url"
                for r in references
            )),
            "request_payload": json.dumps(request, ensure_ascii=False, default=str),
            "submitted_at": db.utcnow(),
        }
    )
    row.setdefault("status", "queued")
    # Price it up front so a queued task already shows its projected cost.
    row.update(pricing.cost_for_row(row).as_row())

    db.upsert_task(conn, row, overwrite=pricing.COST_COLUMNS)
    db.replace_references(conn, task_id, extract_references(content))
    db.log_event(conn, task_id, row.get("status"), "submitted")
    return task_id


def record_response(conn: sqlite3.Connection, response: Any) -> dict[str, Any]:
    """Flatten one tasks.get response and persist it. Returns the row written."""
    row = flatten_task(response)
    task_id = row.get("id")
    if not task_id:
        raise RuntimeError("response has no task id")

    status = (row.get("status") or "").lower()
    row["last_polled_at"] = db.utcnow()
    if is_terminal(status):
        row["completed_at"] = db.utcnow()

    # The response carries the authoritative resolution/duration, so recost
    # against it, merging in request-side fields the response does not echo.
    existing = db.get_task(conn, task_id)
    for key in ("input_video_seconds", "requested_resolution",
                "requested_duration", "has_video_input"):
        if row.get(key) is None and existing is not None and key in existing.keys():
            row[key] = existing[key]
    row.update(pricing.cost_for_row(row).as_row())

    db.upsert_task(conn, row, overwrite=pricing.COST_COLUMNS)
    if status != (db.last_event_status(conn, task_id) or ""):
        db.log_event(conn, task_id, status, row.get("error_message"))
    return row


def poll(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    interval: int = POLL_INTERVAL_SECONDS,
    timeout: int = POLL_TIMEOUT_SECONDS,
    ark_client=None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Poll until the task reaches a terminal state, persisting every response."""
    ark_client = ark_client or ark.make_client()
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        response = ark.get_task(ark_client, task_id)
        db.bump_poll(conn, task_id)
        row = record_response(conn, response)
        status = (row.get("status") or "").lower()

        if is_terminal(status):
            if verbose:
                print(f"[{task_id}] {status}")
            return row
        if verbose:
            print(f"[{task_id}] {status or 'unknown'}, retrying in {interval}s...")
        time.sleep(interval)

    db.log_event(conn, task_id, "timeout", f"no terminal status within {timeout}s")
    raise TimeoutError(f"task {task_id} did not finish within {timeout} seconds")


def run(
    conn: sqlite3.Connection,
    prompt: str,
    *,
    download_dir: str | Path | None = None,
    interval: int = POLL_INTERVAL_SECONDS,
    timeout: int = POLL_TIMEOUT_SECONDS,
    verbose: bool = True,
    ark_client=None,
    **submit_kwargs,
) -> dict[str, Any]:
    """submit + poll in one call."""
    # submit() runs preflight before touching credentials, so call it first and
    # only build a client for polling once the task actually exists.
    task_id = submit(conn, prompt, ark_client=ark_client, **submit_kwargs)
    ark_client = ark_client or ark.make_client()
    row = poll(
        conn, task_id, interval=interval, timeout=timeout,
        verbose=verbose, ark_client=ark_client,
    )
    if download_dir and row.get("video_url"):
        row["local_path"] = download(conn, task_id, download_dir)
    return row


def sync_pending(conn: sqlite3.Connection, *, ark_client=None) -> list[dict[str, Any]]:
    """Refresh every non-terminal task once. Safe to run on a schedule."""
    ark_client = ark_client or ark.make_client()
    results: list[dict[str, Any]] = []
    for task in db.unfinished_tasks(conn):
        task_id = task["id"]
        try:
            response = ark.get_task(ark_client, task_id)
        except Exception as exc:  # keep going; one bad task shouldn't stop the sweep
            db.log_event(conn, task_id, task["status"], f"poll error: {exc}")
            continue
        db.bump_poll(conn, task_id)
        results.append(record_response(conn, response))
    return results


def download(conn: sqlite3.Connection, task_id: str, dest_dir: str | Path) -> str:
    """Download the generated video locally and record the path.

    Ark's video URLs expire, so grab the file if you need it beyond that window.
    """
    row = db.get_task(conn, task_id)
    if row is None:
        raise KeyError(task_id)
    url = row["video_url"]
    if not url:
        raise ValueError(f"task {task_id} has no video_url")

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Prefer what the API actually produced over what we asked for.
    keys = row.keys()
    suffix = (
        (row["fileformat"] if "fileformat" in keys else None)
        or (row["output_format"] if "output_format" in keys else None)
        or (row["requested_output_format"] if "requested_output_format" in keys else None)
        or "mp4"
    ).lstrip(".")
    dest = dest_dir / f"{task_id}.{suffix}"
    urllib.request.urlretrieve(url, dest)

    conn.execute(
        "UPDATE video_tasks SET local_path = ? WHERE id = ?", (str(dest), task_id)
    )
    conn.commit()
    db.log_event(conn, task_id, row["status"], f"downloaded to {dest}")
    return str(dest)


def recost_all(conn: sqlite3.Connection) -> int:
    """Recompute every row's cost against the current price table.

    Run after editing videogen/pricing.py so historical rows pick up corrected
    prices. Rows keep the pricing_version they were costed with.
    """
    updated = 0
    for task in conn.execute("SELECT * FROM video_tasks").fetchall():
        estimate = pricing.cost_for_row(dict(task))
        row = {"id": task["id"], **estimate.as_row()}
        # Written verbatim below, so a note cleared by an exact price goes away.
        # as_row() may legitimately null a field, so write it directly rather
        # than through the COALESCE upsert.
        conn.execute(
            "UPDATE video_tasks SET estimated_cost_usd = ?, cost_basis = ?, "
            "cost_is_estimate = ?, cost_currency = ?, pricing_version = ?, "
            "cost_note = ?, unit_price_per_million_usd = ? WHERE id = ?",
            (
                row["estimated_cost_usd"], row["cost_basis"], row["cost_is_estimate"],
                row["cost_currency"], row["pricing_version"], row["cost_note"],
                row["unit_price_per_million_usd"], task["id"],
            ),
        )
        updated += 1
    conn.commit()
    return updated


def probe_video_seconds(urls: Sequence[str], timeout: int = 30) -> float | None:
    """Total duration of the reference videos, via ffprobe if it is installed.

    Returns None when ffprobe is unavailable or any probe fails, so the caller
    can fall back to an explicit --input-video-seconds.
    """
    import shutil
    import subprocess

    if not urls or shutil.which("ffprobe") is None:
        return None
    total = 0.0
    for url in urls:
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", url],
                capture_output=True, text=True, timeout=timeout, check=True,
            )
            total += float(out.stdout.strip())
        except Exception:
            return None
    return round(total, 3)
