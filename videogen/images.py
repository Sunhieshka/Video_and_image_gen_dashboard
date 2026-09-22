"""Image generation: call, price, persist.

Unlike video, the image API is synchronous -- one call returns the images -- so
there is no task id from the provider and nothing to poll. Each request gets a
locally generated id, its own row in image_tasks, and one row per produced
image in image_outputs.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import client as ark
from . import db
from . import image_pricing as ip
from .flatten import to_dict

TASKS_TABLE = "image_tasks"


def new_task_id() -> str:
    return f"img-{time.strftime('%Y%m%d%H%M%S')}-{os.urandom(4).hex()}"


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    return [value] if isinstance(value, str) else list(value)


def flatten_response(response: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Split a response into (task columns, one dict per produced image)."""
    data = to_dict(response)

    row: dict[str, Any] = {}
    for key, value in data.items():
        if key in ("data", "usage", "error", "tool"):
            continue
        row[key] = value if isinstance(value, (str, int, float, type(None))) else (
            int(value) if isinstance(value, bool) else json.dumps(value, default=str)
        )

    usage = to_dict(data.get("usage")) if data.get("usage") else {}
    for key in ("generated_images", "input_images", "output_tokens", "total_tokens"):
        if usage.get(key) is not None:
            row[key] = usage[key]

    error = to_dict(data.get("error")) if data.get("error") else {}
    if error:
        row["error_code"] = error.get("code")
        row["error_message"] = error.get("message")

    images: list[dict[str, Any]] = []
    for i, item in enumerate(data.get("data") or []):
        img = to_dict(item)
        size = img.get("size")
        pixels = ip.parse_pixels(size)
        width = height = None
        if pixels and size and "x" in str(size).lower():
            parts = str(size).lower().replace("*", "x").split("x")
            try:
                width, height = int(parts[0]), int(parts[1])
            except (ValueError, IndexError):
                pass
        images.append({
            "position": i,
            "url": img.get("url"),
            "size": size,
            "width": width,
            "height": height,
            "pixels": pixels,
            "output_format": img.get("output_format"),
            "description": img.get("description"),
            "name": img.get("name"),
            "z_index": img.get("z_index"),
        })

    row["raw_response"] = json.dumps(data, ensure_ascii=False, default=str)
    return row, images


def generate(
    conn: sqlite3.Connection,
    prompt: str,
    *,
    model: str | None = None,
    image: str | Sequence[str] | None = None,
    size: str = "2K",
    output_format: str = "png",
    response_format: str = "url",
    watermark: bool = False,
    seed: int | None = None,
    guidance_scale: float | None = None,
    optimize_prompt: bool | None = None,
    sequential_image_generation: str | None = None,
    extra: Mapping[str, Any] | None = None,
    download_dir: str | Path | None = None,
    strict: bool = True,
    ark_client=None,
) -> dict[str, Any]:
    """Generate images, price them, and store the result. Returns the row."""
    model = model or ark.DEFAULT_IMAGE_MODEL
    inputs = _as_list(image)

    # The models take different size sets: pro tops out at 2K, while 5.0 and
    # 4.5 start there. Catch a bad pairing before it costs anything.
    size = ip.normalize_size(size) or size
    errors, warnings = ip.validate_image_request(model, size)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors and strict:
        raise ValueError("; ".join(errors))
    for error in errors:
        print(f"warning (strict=False): {error}", file=sys.stderr)

    request: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "output_format": output_format,
        "response_format": response_format,
        "watermark": watermark,
    }
    if inputs:
        request["image"] = inputs[0] if len(inputs) == 1 else inputs
    if seed is not None:
        request["seed"] = seed
    if guidance_scale is not None:
        request["guidance_scale"] = guidance_scale
    if optimize_prompt is not None:
        request["optimize_prompt"] = optimize_prompt
    if sequential_image_generation:
        request["sequential_image_generation"] = sequential_image_generation
    if extra:
        request.update(extra)

    task_id = new_task_id()
    started = time.monotonic()
    ark_client = ark_client or ark.make_client()

    base_row: dict[str, Any] = {
        "id": task_id,
        "model": model,
        "prompt": prompt,
        "size": size,
        "output_format": output_format,
        "response_format": response_format,
        "watermark": int(watermark),
        "seed": seed,
        "guidance_scale": guidance_scale,
        "optimize_prompt": None if optimize_prompt is None else int(optimize_prompt),
        "sequential_image_generation": sequential_image_generation,
        "layer_decomposition": 0,
        "input_images": len(inputs),
        "request_payload": json.dumps(request, ensure_ascii=False, default=str),
        "submitted_at": db.utcnow(),
    }

    try:
        response = ark.generate_image(ark_client, **request)
    except Exception as exc:
        row = {
            **base_row,
            "status": "failed",
            "error_code": type(exc).__name__,
            "error_message": str(exc),
            "completed_at": db.utcnow(),
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
        row.update(ip.cost_for_image_row(row).as_row())
        db.upsert_task(conn, row, TASKS_TABLE)
        _store_inputs(conn, task_id, inputs, model)
        raise

    resp_row, images = flatten_response(response)
    row = {**base_row, **resp_row, "id": task_id}
    row["status"] = "failed" if row.get("error_code") else "succeeded"
    row["completed_at"] = db.utcnow()
    row["latency_ms"] = int((time.monotonic() - started) * 1000)
    row.setdefault("input_images", len(inputs))

    cost = ip.cost_for_image_row(row, sizes=[i["size"] for i in images])
    row.update(cost.as_row())

    db.upsert_task(conn, row, TASKS_TABLE)
    _store_outputs(conn, task_id, images, cost, model)
    _store_inputs(conn, task_id, inputs, model)

    if download_dir and images:
        download(conn, task_id, download_dir)

    return dict(get(conn, task_id) or row)


def _store_outputs(conn, task_id, images, cost, model) -> None:
    price = ip.IMAGE_PRICING.get(ip.image_model_family(model) or "")
    conn.execute("DELETE FROM image_outputs WHERE task_id = ?", (task_id,))
    conn.executemany(
        "INSERT INTO image_outputs (task_id, position, url, size, width, height, "
        "pixels, output_format, rate_usd, description, name, z_index) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(task_id, i["position"], i["url"], i["size"], i["width"], i["height"],
          i["pixels"], i["output_format"],
          price.output_rate(i["pixels"]) if price else cost.output_rate,
          i["description"], i["name"], i["z_index"]) for i in images],
    )
    conn.commit()


def _store_inputs(conn, task_id, inputs, model) -> None:
    price = ip.IMAGE_PRICING.get(ip.image_model_family(model) or "")
    free = price.input_free_count if price else 0
    conn.execute("DELETE FROM image_inputs WHERE task_id = ?", (task_id,))
    conn.executemany(
        "INSERT INTO image_inputs (task_id, position, url, billable) VALUES (?,?,?,?)",
        [(task_id, i, url, int(i >= free)) for i, url in enumerate(inputs)],
    )
    conn.commit()


def get(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT * FROM {TASKS_TABLE} WHERE id = ?", (task_id,)).fetchone()


def outputs(conn: sqlite3.Connection, task_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM image_outputs WHERE task_id = ? ORDER BY position",
        (task_id,)).fetchall()


def list_tasks(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM v_image_tasks ORDER BY created_at_utc DESC LIMIT ?",
        (limit,)).fetchall()


def download(conn: sqlite3.Connection, task_id: str, dest_dir: str | Path) -> list[str]:
    """Save the generated images locally. Ark's URLs expire."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for row in outputs(conn, task_id):
        if not row["url"]:
            continue
        suffix = (row["output_format"] or "png").lstrip(".")
        path = dest_dir / f"{task_id}-{row['position']}.{suffix}"
        urllib.request.urlretrieve(row["url"], path)
        conn.execute(
            "UPDATE image_outputs SET local_path = ? WHERE task_id = ? AND position = ?",
            (str(path), task_id, row["position"]))
        saved.append(str(path))
    conn.commit()
    return saved


def recost_all(conn: sqlite3.Connection) -> int:
    """Reprice every stored image task against the current table."""
    updated = 0
    for task in conn.execute(f"SELECT * FROM {TASKS_TABLE}").fetchall():
        sizes = [r["size"] for r in outputs(conn, task["id"])]
        cost = ip.cost_for_image_row(dict(task), sizes=sizes)
        row = cost.as_row()
        conn.execute(
            f"UPDATE {TASKS_TABLE} SET estimated_cost_usd = ?, cost_basis = ?, "
            "cost_is_estimate = ?, cost_currency = ?, pricing_version = ?, "
            "cost_note = ?, output_rate_usd = ?, output_cost_usd = ?, "
            "input_cost_usd = ? WHERE id = ?",
            (row["estimated_cost_usd"], row["cost_basis"], row["cost_is_estimate"],
             row["cost_currency"], row["pricing_version"], row["cost_note"],
             row["output_rate_usd"], row["output_cost_usd"], row["input_cost_usd"],
             task["id"]),
        )
        updated += 1
    conn.commit()
    return updated
