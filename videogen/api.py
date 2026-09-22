"""HTTP API for the web UI.

Wraps the same workflow the CLI uses. Generation is asynchronous: POST /generate
returns a task id immediately and a background poller keeps the database up to
date, so the browser just polls GET /tasks/{id}.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, image_pricing, images as image_workflow, models, pricing, workflow
from .env import load_env
from .errors import ProviderError, translate as translate_error

load_env()

DB_PATH = db.DEFAULT_DB_PATH
POLL_SECONDS = 10
ROOT = Path(__file__).resolve().parent.parent
UI_DIST = ROOT / "ui" / "dist"

UPLOAD_DIR = Path(os.environ.get("VIDEOGEN_UPLOAD_DIR", ROOT / "uploads"))
MAX_UPLOAD_BYTES = int(os.environ.get("VIDEOGEN_MAX_UPLOAD_MB", "256")) * 1024 * 1024

# Ark fetches reference media from the URL we hand it, so that URL has to be
# reachable from the internet. A localhost address will not work. Set
# VIDEOGEN_PUBLIC_BASE_URL to a tunnel or deployment origin to make uploads
# usable; /api/upload reports whether the URL it returns is publicly reachable.
PUBLIC_BASE_URL = os.environ.get("VIDEOGEN_PUBLIC_BASE_URL", "").rstrip("/")

KIND_BY_PREFIX = {
    "image": "image_url",
    "video": "video_url",
    "audio": "audio_url",
}


class Poller:
    """Refreshes unfinished tasks on a timer, so the UI only has to read."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            conn = None
            try:
                conn = get_conn()
                if db.unfinished_tasks(conn):
                    workflow.sync_pending(conn)
                    self.last_error = None
            except Exception as exc:  # never let the thread die
                self.last_error = str(translate_error(exc))
            finally:
                if conn is not None:
                    conn.close()
            self._stop.wait(POLL_SECONDS)


poller = Poller()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    poller.start()
    yield
    poller.stop()


app = FastAPI(title="Video generation dashboard", lifespan=lifespan)

# The Vite dev server runs on a different port during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_conn() -> sqlite3.Connection:
    conn = db.connect(DB_PATH, check_same_thread=False)
    db.init_db(conn)
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


# ----------------------------------------------------------------- schemas


class Reference(BaseModel):
    type: Literal["image_url", "video_url", "audio_url"]
    url: str
    role: str | None = None


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model: str | None = None
    references: list[Reference] = []
    resolution: str | None = None
    ratio: str = "16:9"
    duration: int = 5
    generate_audio: bool = True
    output_format: str | None = None
    omni_reference_task_type: str | None = None
    input_video_seconds: float | None = None


class PriceRequest(BaseModel):
    model: str | None = None
    resolution: str | None = None
    duration: float = 5
    input_video_seconds: float | None = None
    has_video_input: bool = False
    total_tokens: int | None = None


# ----------------------------------------------------------- background poll


# ------------------------------------------------------------------ routes


@app.get("/api/models")
def list_models() -> dict[str, Any]:
    """Families, capabilities and headline prices, for the form's selects."""
    out = []
    for entry in models.summary():
        caps = entry["capabilities"]
        out.append({
            "family": entry["family"],
            "model_id": entry["model_id"],
            "label": entry["family"].replace("seedance-", "Seedance ").title()
                     .replace("Seedance ", "Seedance "),
            "aliases": entry["aliases"],
            "resolutions": list(caps.resolutions),
            "input_video_max_seconds": caps.input_video_max_seconds,
            "omni_reference": caps.omni_reference,
            "prices": {
                res: {
                    "per_video_5s": p.per_video_ref,
                    "per_second": p.per_second,
                    "per_million_tokens": pricing.TOKEN_RATES
                        .get(entry["family"], {}).get(res),
                }
                for res, p in entry["prices"].items()
            },
        })
    return {"models": out, "pricing_version": pricing.PRICING_VERSION}


@app.post("/api/price")
def quote(req: PriceRequest) -> dict[str, Any]:
    """Cost for a configuration.

    With token usage the answer is exact (unit / 1e6 * tokens); without it,
    which is the case before a task runs, it falls back to the published
    per-video table and says so.
    """
    model = req.model or models.default_model()
    has_video = req.has_video_input or bool(req.input_video_seconds)

    if req.total_tokens:
        est = pricing.cost_from_tokens(
            model, req.resolution, req.total_tokens, has_video)
    else:
        est = pricing.estimate_cost(
            model, req.resolution, req.duration, req.input_video_seconds)
        if est.amount is not None:
            est.is_estimate = True
            est.note = "; ".join(filter(None, [
                est.note,
                "projected; final price is billed on actual token usage",
            ]))

    return {
        "amount": est.amount,
        "basis": est.basis,
        "is_estimate": est.is_estimate,
        "note": est.note,
        "currency": pricing.CURRENCY,
        "unit_price_per_million": est.unit_price_per_million
            or pricing.token_rate(model, req.resolution, has_video),
    }


@app.post("/api/generate")
def generate(req: GenerateRequest) -> dict[str, Any]:
    conn = get_conn()
    try:
        task_id = workflow.submit(
            conn,
            req.prompt,
            model=req.model,
            references=[r.model_dump() for r in req.references],
            ratio=req.ratio,
            duration=req.duration,
            resolution=req.resolution,
            generate_audio=req.generate_audio,
            output_format=req.output_format,
            omni_reference_task_type=req.omni_reference_task_type,
            input_video_seconds=req.input_video_seconds,
        )
    except ValueError as exc:            # unsupported combination
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:         # Ark said no -- pass its reason on
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
    except RuntimeError as exc:          # missing credentials
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        conn.close()

    poller.start()
    return {"task_id": task_id}


@app.get("/api/tasks")
def list_tasks(
    status: str | None = None,
    model: str | None = None,
    resolution: str | None = None,
    search: str | None = None,
    estimated_only: bool = False,
    limit: int = Query(200, le=1000),
) -> dict[str, Any]:
    """Filtered task list plus totals for exactly the same filter."""
    conn = get_conn()
    try:
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if model:
            where.append("model = ?")
            params.append(model)
        if resolution:
            where.append("resolution = ?")
            params.append(resolution)
        if search:
            where.append("(prompt LIKE ? OR id LIKE ?)")
            params += [f"%{search}%", f"%{search}%"]
        if estimated_only:
            where.append("cost_is_estimate = 1")
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        rows = conn.execute(
            f"SELECT * FROM video_tasks {clause} "
            "ORDER BY COALESCE(created_at, 0) DESC, submitted_at DESC LIMIT ?",
            [*params, limit],
        ).fetchall()

        totals = conn.execute(
            f"SELECT COUNT(*) AS tasks, "
            "COALESCE(SUM(estimated_cost_usd), 0) AS cost_usd, "
            "COALESCE(SUM(total_tokens), 0) AS tokens, "
            "COALESCE(SUM(cost_is_estimate), 0) AS estimated_rows, "
            "COALESCE(SUM(status = 'succeeded'), 0) AS succeeded, "
            "COALESCE(SUM(status = 'failed'), 0) AS failed "
            f"FROM video_tasks {clause}",
            params,
        ).fetchone()

        options = {
            "statuses": [r[0] for r in conn.execute(
                "SELECT DISTINCT status FROM video_tasks WHERE status IS NOT NULL "
                "ORDER BY status")],
            "models": [r[0] for r in conn.execute(
                "SELECT DISTINCT model FROM video_tasks WHERE model IS NOT NULL "
                "ORDER BY model")],
            "resolutions": [r[0] for r in conn.execute(
                "SELECT DISTINCT resolution FROM video_tasks "
                "WHERE resolution IS NOT NULL ORDER BY resolution")],
        }
        return {
            "tasks": [dict(r) for r in rows],
            "totals": dict(totals),
            "filter_options": options,
        }
    finally:
        conn.close()


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    conn = get_conn()
    try:
        row = row_to_dict(db.get_task(conn, task_id))
        if row is None:
            raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
        row["references"] = [
            dict(r) for r in conn.execute(
                "SELECT position, ref_type, role, url FROM task_references "
                "WHERE task_id = ? ORDER BY position", (task_id,))
        ]
        row["events"] = [
            dict(r) for r in conn.execute(
                "SELECT observed_at, status, detail FROM task_events "
                "WHERE task_id = ? ORDER BY event_id", (task_id,))
        ]
        return row
    finally:
        conn.close()


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    conn = get_conn()
    try:
        total = dict(conn.execute("SELECT * FROM v_spend_total").fetchone())
        by_day = [dict(r) for r in conn.execute(
            "SELECT * FROM v_spend_by_day LIMIT 30")]
        return {
            "total": total,
            "by_day": by_day,
            "poller_error": poller.last_error,
            "pricing_version": pricing.PRICING_VERSION,
        }
    finally:
        conn.close()


# ------------------------------------------------------------------ images


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model: str | None = None
    image: list[str] = []
    size: str = "2K"
    output_format: str = "png"
    response_format: str = "url"
    watermark: bool = False
    seed: int | None = None
    guidance_scale: float | None = None
    sequential_image_generation: str | None = None


class ImagePriceRequest(BaseModel):
    model: str | None = None
    size: str | None = None
    generated_images: int = 1
    input_images: int = 0


@app.get("/api/image-models")
def list_image_models() -> dict[str, Any]:
    out = []
    for family, price in image_pricing.IMAGE_PRICING.items():
        out.append({
            "family": family,
            "model_id": price.model_id,
            "output_small": price.output_small,
            "output_large": price.output_large,
            "tiered": price.output_small != price.output_large,
            "input_per_image": price.input_per_image,
            "input_free_count": price.input_free_count,
            "sizes": list(price.sizes),
        })
    return {
        "models": out,
        "pixel_tier": image_pricing.PIXEL_TIER,
        "sizes": ["1K", "1.5K", "2K", "4K"],
        "pricing_version": image_pricing.IMAGE_PRICING_VERSION,
    }


@app.post("/api/images/price")
def quote_image(req: ImagePriceRequest) -> dict[str, Any]:
    model = req.model or ark_client_defaults()
    est = image_pricing.estimate_image_cost(
        model,
        sizes=[req.size] * max(1, req.generated_images) if req.size else None,
        generated_images=req.generated_images,
        input_images=req.input_images,
    )
    return {
        "amount": est.amount,
        "basis": est.basis,
        "is_estimate": est.is_estimate,
        "note": est.note,
        "output_rate": est.output_rate,
        "output_cost": est.output_cost,
        "input_cost": est.input_cost,
        "currency": image_pricing.CURRENCY,
    }


def ark_client_defaults() -> str:
    from .client import DEFAULT_IMAGE_MODEL
    return DEFAULT_IMAGE_MODEL


@app.post("/api/images/generate")
def generate_image(req: ImageGenerateRequest) -> dict[str, Any]:
    conn = get_conn()
    try:
        row = image_workflow.generate(
            conn,
            req.prompt,
            model=req.model,
            image=req.image or None,
            size=req.size,
            output_format=req.output_format,
            response_format=req.response_format,
            watermark=req.watermark,
            seed=req.seed,
            guidance_scale=req.guidance_scale,
            sequential_image_generation=req.sequential_image_generation,
        )
        row["outputs"] = [dict(o) for o in image_workflow.outputs(conn, row["id"])]
        return row
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        conn.close()


@app.get("/api/images")
def list_images(
    status: str | None = None,
    model: str | None = None,
    size: str | None = None,
    search: str | None = None,
    limit: int = Query(200, le=1000),
) -> dict[str, Any]:
    conn = get_conn()
    try:
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if model:
            where.append("model = ?")
            params.append(model)
        if size:
            where.append("size = ?")
            params.append(size)
        if search:
            where.append("(prompt LIKE ? OR id LIKE ?)")
            params += [f"%{search}%", f"%{search}%"]
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM image_tasks {clause} "
            "ORDER BY COALESCE(created, 0) DESC, submitted_at DESC LIMIT ?",
            [*params, limit])]
        for row in rows:
            row["outputs"] = [dict(o) for o in
                              image_workflow.outputs(conn, row["id"])]

        totals = dict(conn.execute(
            "SELECT COUNT(*) AS tasks, "
            "COALESCE(SUM(generated_images), 0) AS images, "
            "COALESCE(SUM(estimated_cost_usd), 0) AS cost_usd, "
            "COALESCE(SUM(total_tokens), 0) AS tokens, "
            "COALESCE(SUM(cost_is_estimate), 0) AS estimated_rows, "
            "COALESCE(SUM(status = 'succeeded'), 0) AS succeeded, "
            "COALESCE(SUM(status = 'failed'), 0) AS failed "
            f"FROM image_tasks {clause}", params).fetchone())

        options = {
            "statuses": [r[0] for r in conn.execute(
                "SELECT DISTINCT status FROM image_tasks WHERE status IS NOT NULL "
                "ORDER BY status")],
            "models": [r[0] for r in conn.execute(
                "SELECT DISTINCT model FROM image_tasks WHERE model IS NOT NULL "
                "ORDER BY model")],
            "sizes": [r[0] for r in conn.execute(
                "SELECT DISTINCT size FROM image_tasks WHERE size IS NOT NULL "
                "ORDER BY size")],
        }
        return {"tasks": rows, "totals": totals, "filter_options": options}
    finally:
        conn.close()


@app.get("/api/images/{task_id}")
def get_image(task_id: str) -> dict[str, Any]:
    conn = get_conn()
    try:
        row = row_to_dict(image_workflow.get(conn, task_id))
        if row is None:
            raise HTTPException(status_code=404, detail=f"no such image task: {task_id}")
        row["outputs"] = [dict(o) for o in image_workflow.outputs(conn, task_id)]
        row["inputs"] = [dict(r) for r in conn.execute(
            "SELECT position, url, billable FROM image_inputs WHERE task_id = ? "
            "ORDER BY position", (task_id,))]
        return row
    finally:
        conn.close()


# ----------------------------------------------------------------- uploads


def _reference_kind(filename: str, content_type: str | None) -> str | None:
    """Map a file to the Ark content type it should be sent as.

    Browsers send a real media type; curl and other clients often send
    application/octet-stream, so fall back to the filename extension rather
    than rejecting a perfectly good video.
    """
    for candidate in (content_type, mimetypes.guess_type(filename)[0]):
        if not candidate:
            continue
        kind = KIND_BY_PREFIX.get(candidate.split("/")[0])
        if kind:
            return kind
    return None


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """Store uploaded reference media and return URLs to pass to Ark.

    Files are content-hashed, so uploading the same file twice reuses one copy.
    """
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    for upload_file in files:
        kind = _reference_kind(upload_file.filename or "", upload_file.content_type)
        if kind is None:
            raise HTTPException(
                status_code=400,
                detail=f"{upload_file.filename}: not an image, video or audio file",
            )

        digest = hashlib.sha256()
        suffix = Path(upload_file.filename or "").suffix.lower()
        tmp_path = UPLOAD_DIR / f".incoming-{os.urandom(8).hex()}{suffix}"
        size = 0
        try:
            with tmp_path.open("wb") as out:
                while chunk := await upload_file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"{upload_file.filename} exceeds "
                                   f"{MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
                        )
                    digest.update(chunk)
                    out.write(chunk)

            name = f"{digest.hexdigest()[:32]}{suffix}"
            final = UPLOAD_DIR / name
            if final.exists():
                tmp_path.unlink()
            else:
                shutil.move(str(tmp_path), str(final))
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

        seconds = None
        if kind == "video_url":
            seconds = workflow.probe_video_seconds([str(final)])

        results.append({
            "filename": upload_file.filename,
            "type": kind,
            "url": f"{PUBLIC_BASE_URL}/files/{name}" if PUBLIC_BASE_URL
                   else f"/files/{name}",
            "size": size,
            "duration_seconds": seconds,
        })

    return {
        "files": results,
        # The UI warns when Ark will not be able to fetch these URLs.
        "publicly_reachable": bool(PUBLIC_BASE_URL),
        "public_base_url": PUBLIC_BASE_URL or None,
    }


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {
        "publicly_reachable": bool(PUBLIC_BASE_URL),
        "public_base_url": PUBLIC_BASE_URL or None,
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    }


@app.get("/files/{name}")
def serve_upload(name: str) -> FileResponse:
    """Serve an uploaded file.

    A route rather than a StaticFiles mount, because the mount would bind the
    directory at import time. `name` comes from the URL, so resolve it and
    confirm it really sits inside the upload directory before serving.
    """
    root = UPLOAD_DIR.resolve()
    path = (root / name).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="no such file")
    return FileResponse(path)


# --------------------------------------------------------------- static UI


if UI_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(UI_DIST / "index.html")
