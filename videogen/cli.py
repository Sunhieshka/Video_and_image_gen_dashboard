"""Command line entry point: python -m videogen <command>"""

from __future__ import annotations

import argparse
import json
import sys

from . import db, image_pricing, images as image_workflow, models, pricing, workflow
from .env import load_env
from .errors import ProviderError


def _parse_ref(raw: str, ref_type: str, default_role: str) -> dict[str, str]:
    url, _, role = raw.partition("::")
    return {"type": ref_type, "url": url, "role": role or default_role}


def _fmt_cost(row) -> str:
    """Render a cost, marking interpolated values with ~."""
    if row is None:
        return "-"
    keys = row.keys() if hasattr(row, "keys") else row
    amount = row["estimated_cost_usd"] if "estimated_cost_usd" in keys else None
    if amount is None:
        return "-"
    mark = "~" if ("cost_is_estimate" in keys and row["cost_is_estimate"]) else ""
    return f"{mark}${amount:.4f}"


def _print_rows(rows) -> None:
    if not rows:
        print("(no rows)")
        return
    for r in rows:
        print(
            f"{r['id']}  {r['status'] or '?':<10} {r['model']}  "
            f"{r['ratio'] or '-'} {r['duration'] or '-'}s {r['resolution'] or '-'}  "
            f"tokens={r['total_tokens'] or '-'}  {_fmt_cost(r):>10}  "
            f"{r['created_at_utc'] or ''}"
        )
    total = sum((r['estimated_cost_usd'] or 0) for r in rows)
    print(f"{len(rows)} task(s), ${total:.4f} total")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="videogen")
    parser.add_argument("--db", default=db.DEFAULT_DB_PATH, help="SQLite file path")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the database schema")

    for name, help_text in (("submit", "create a task"), ("run", "create a task and poll it")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("prompt", help="text prompt, or @file to read from a file")
        p.add_argument(
            "--model", default=None,
            help="model id, or an alias: 2.5 | 2.0 | fast | mini",
        )
        p.add_argument(
            "--no-strict", action="store_true",
            help="warn instead of failing on an unsupported combination",
        )
        p.add_argument("--ratio", default="16:9")
        p.add_argument("--duration", type=int, default=5)
        p.add_argument("--no-audio", action="store_true")
        p.add_argument("--output-format", default=None, help="e.g. mov")
        p.add_argument("--reference-task-type", default=None, help="omni_reference_task_type")
        p.add_argument("--image", action="append", default=[], metavar="URL[::ROLE]")
        p.add_argument("--video", action="append", default=[], metavar="URL[::ROLE]")
        p.add_argument("--resolution", default=None, help="480p|720p|1080p|4k")
        p.add_argument(
            "--input-video-seconds", type=float, default=None,
            help="total duration of reference videos; drives the video-input surcharge",
        )
        p.add_argument(
            "--probe-input", action="store_true",
            help="measure reference-video duration with ffprobe instead",
        )
        if name == "run":
            p.add_argument("--download-dir", default=None)

    p = sub.add_parser("poll", help="poll one task until it finishes")
    p.add_argument("task_id")
    p.add_argument("--interval", type=int, default=workflow.POLL_INTERVAL_SECONDS)
    p.add_argument("--timeout", type=int, default=workflow.POLL_TIMEOUT_SECONDS)

    sub.add_parser("sync", help="refresh every unfinished task once")

    p = sub.add_parser("list", help="list stored tasks")
    p.add_argument("--status")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("show", help="print one task as JSON")
    p.add_argument("task_id")

    p = sub.add_parser("download", help="download a finished task's video")
    p.add_argument("task_id")
    p.add_argument("--dir", default="videos")

    p = sub.add_parser("export", help="export all tasks to CSV")
    p.add_argument("path")

    p = sub.add_parser("cost", help="spend summary")
    p.add_argument("--by", choices=["day", "model", "total"], default="day")

    sub.add_parser("recost", help="recompute costs against the current price table")

    sub.add_parser("models", help="list model families, capabilities and prices")

    p = sub.add_parser("image", help="generate an image")
    p.add_argument("prompt", help="text prompt, or @file to read from a file")
    p.add_argument("--model", default=None, help="image model id")
    p.add_argument("--size", default="2K", help="1K | 2K | 4K, or WxH")
    p.add_argument("--output-format", default="png")
    p.add_argument("--watermark", action="store_true")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--input", action="append", default=[], metavar="URL",
                   help="input image for image-to-image; repeatable")
    p.add_argument("--download-dir", default=None)

    p = sub.add_parser("images", help="list stored image generations")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("image-price", help="quote an image cost without calling the API")
    p.add_argument("--model", default=None)
    p.add_argument("--size", default="2K")
    p.add_argument("--images", type=int, default=1, help="images to generate")
    p.add_argument("--inputs", type=int, default=0, help="input images supplied")
    p.add_argument("--compare", action="store_true",
                   help="quote across every image model")

    p = sub.add_parser("price", help="quote a cost without calling the API")
    p.add_argument("--model", default=None, help="model id or alias (2.5|2.0|fast|mini)")
    p.add_argument(
        "--compare", action="store_true",
        help="quote the same config across every model instead",
    )
    p.add_argument("--resolution", default="720p")
    p.add_argument("--duration", type=float, default=5)
    p.add_argument("--input-video-seconds", type=float, default=None)
    p.add_argument(
        "--tokens", type=int, default=None,
        help="total_tokens from a finished task; gives the exact billed price",
    )
    p.add_argument(
        "--with-video", action="store_true",
        help="use the with-video-input token rate",
    )

    args = parser.parse_args(argv)
    # Pick up ARK_API_KEY and friends from .env; real env vars still win.
    load_env()
    conn = db.connect(args.db)

    if args.command == "init":
        db.init_db(conn)
        print(f"initialized {args.db} ({len(db.columns(conn))} columns in video_tasks)")
        return 0

    db.init_db(conn)  # idempotent; keeps every command safe on a fresh file

    if args.command in ("submit", "run"):
        prompt = args.prompt
        if prompt.startswith("@"):
            with open(prompt[1:], encoding="utf-8") as fh:
                prompt = fh.read()
        references = [_parse_ref(r, "image_url", "reference_image") for r in args.image]
        references += [_parse_ref(r, "video_url", "reference_video") for r in args.video]

        input_seconds = args.input_video_seconds
        if input_seconds is None and args.probe_input:
            input_seconds = workflow.probe_video_seconds(
                [r["url"] for r in references if r["type"] == "video_url"]
            )
            if input_seconds is None:
                print("warning: could not probe input video duration (is ffprobe "
                      "installed?); cost will ignore the video-input surcharge",
                      file=sys.stderr)

        kwargs = dict(
            references=references,
            ratio=args.ratio,
            duration=args.duration,
            resolution=args.resolution,
            generate_audio=not args.no_audio,
            output_format=args.output_format,
            omni_reference_task_type=args.reference_task_type,
            input_video_seconds=input_seconds,
            model=args.model,
            strict=not args.no_strict,
        )

        try:
            if args.command == "submit":
                task_id = workflow.submit(conn, prompt, **kwargs)
            else:
                row = workflow.run(conn, prompt, download_dir=args.download_dir, **kwargs)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except ProviderError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 4
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3

        if args.command == "submit":
            stored = db.get_task(conn, task_id)
            print(task_id)
            print(f"projected cost: {_fmt_cost(stored)}")
        else:
            keys = ("id", "status", "video_url", "local_path",
                    "estimated_cost_usd", "cost_basis", "cost_note")
            print(json.dumps({k: row.get(k) for k in keys}, indent=2))
        return 0

    if args.command == "poll":
        row = workflow.poll(conn, args.task_id, interval=args.interval, timeout=args.timeout)
        print(json.dumps({k: row.get(k) for k in ("id", "status", "video_url")}, indent=2))
        return 0 if row.get("status") == "succeeded" else 1

    if args.command == "sync":
        rows = workflow.sync_pending(conn)
        print(f"refreshed {len(rows)} task(s)")
        for r in rows:
            print(f"  {r['id']}  {r.get('status')}")
        return 0

    if args.command == "list":
        _print_rows(db.list_tasks(conn, status=args.status, limit=args.limit))
        return 0

    if args.command == "show":
        row = db.get_task(conn, args.task_id)
        if row is None:
            print(f"no such task: {args.task_id}", file=sys.stderr)
            return 1
        print(json.dumps(dict(row), indent=2, ensure_ascii=False))
        return 0

    if args.command == "download":
        print(workflow.download(conn, args.task_id, args.dir))
        return 0

    if args.command == "cost":
        if args.by == "total":
            row = conn.execute("SELECT * FROM v_spend_total").fetchone()
            print(f"tasks          {row['tasks']}")
            print(f"cost           ${row['cost_usd'] or 0:.4f}")
            print(f"avg per task   ${row['avg_cost_usd'] or 0:.4f}")
            print(f"tokens         {row['tokens'] or 0:,}")
            if row["estimated_rows"]:
                print(f"note           {row['estimated_rows']} row(s) use interpolated pricing")
            return 0
        if args.by == "model":
            rows = conn.execute(
                "SELECT model, resolution, COUNT(*) AS tasks, "
                "ROUND(SUM(COALESCE(estimated_cost_usd,0)),4) AS cost_usd "
                "FROM video_tasks GROUP BY model, resolution ORDER BY cost_usd DESC"
            ).fetchall()
            for r in rows:
                print(f"{r['model'] or '?':<34} {r['resolution'] or '-':<7} "
                      f"{r['tasks']:>4} tasks  ${r['cost_usd'] or 0:>9.4f}")
            return 0
        for r in conn.execute("SELECT * FROM v_spend_by_day").fetchall():
            print(f"{r['day'] or '?'}  {r['model'] or '?':<34} {r['resolution'] or '-':<7} "
                  f"{r['tasks']:>3} tasks  {r['failed']:>2} failed  ${r['cost_usd'] or 0:>9.4f}")
        return 0

    if args.command == "models":
        for entry in models.summary():
            caps = entry["capabilities"]
            print(f"\n{entry['family']}")
            print(f"  model id    {entry['model_id'] or '(set via env or pass --model)'}")
            print(f"  aliases     {', '.join(entry['aliases'])}")
            print(f"  resolutions {', '.join(caps.resolutions)}")
            print(f"  video input up to {caps.input_video_max_seconds:g}s "
                  f"(flat price to {caps.input_video_flat_until_seconds:g}s)")
            omni = {True: "yes", False: "no", None: "unverified"}[caps.omni_reference]
            print(f"  omni ref    {omni}")
            print("  price       " + "  ".join(
                f"{res}=${p.per_video_ref:.2f}/5s" for res, p in entry["prices"].items()
            ))
            rates = pricing.TOKEN_RATES.get(entry["family"], {})
            print("  per 1M tok  " + "  ".join(
                f"{res}=${r[0]:.2f}/${r[1]:.2f}" for res, r in rates.items()
            ) + "   (no video / with video)")
        print("\nPrices are for 5s output with no video input. "
              "Use `price --compare` to quote a specific config.")
        return 0

    if args.command == "image":
        prompt = args.prompt
        if prompt.startswith("@"):
            with open(prompt[1:], encoding="utf-8") as fh:
                prompt = fh.read()
        try:
            row = image_workflow.generate(
                conn, prompt, model=args.model, size=args.size,
                output_format=args.output_format, watermark=args.watermark,
                seed=args.seed, image=args.input or None,
                download_dir=args.download_dir,
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except ProviderError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 4
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3
        print(row["id"])
        for out in image_workflow.outputs(conn, row["id"]):
            print(f"  [{out['position']}] {out['size']}  {out['url']}")
            if out["local_path"]:
                print(f"       saved to {out['local_path']}")
        print(f"price: ${row['estimated_cost_usd']:.4f} "
              f"({row['generated_images']} image(s) at "
              f"${row['output_rate_usd']:.3f})")
        return 0

    if args.command == "images":
        rows = image_workflow.list_tasks(conn, limit=args.limit)
        if not rows:
            print("(no rows)")
            return 0
        for r in rows:
            print(f"{r['id']}  {r['status'] or '?':<10} {r['model']}  "
                  f"{r['size'] or '-':<5} {r['first_size'] or '-':<10} "
                  f"{r['generated_images'] or 0} img  "
                  f"${r['estimated_cost_usd'] or 0:>7.4f}  {r['created_at_utc'] or ''}")
        total = sum((r["estimated_cost_usd"] or 0) for r in rows)
        print(f"{len(rows)} request(s), ${total:.4f} total")
        return 0

    if args.command == "image-price":
        from .client import DEFAULT_IMAGE_MODEL

        if args.compare:
            print(f"{args.size} / {args.images} image(s) / {args.inputs} input(s)")
            for family, price in image_pricing.IMAGE_PRICING.items():
                est = image_pricing.estimate_image_cost(
                    family, sizes=[args.size] * args.images,
                    generated_images=args.images, input_images=args.inputs)
                detail = (f"${est.amount:.4f}" if est.amount is not None
                          else (est.note or "not supported"))
                print(f"  {family:<20} {detail}"
                      f"   ${price.output_small:.3f}/${price.output_large:.3f} per image")
            return 0

        model = args.model or DEFAULT_IMAGE_MODEL
        est = image_pricing.estimate_image_cost(
            model, sizes=[args.size] * args.images,
            generated_images=args.images, input_images=args.inputs)
        if est.amount is None:
            print(f"no price: {est.note}", file=sys.stderr)
            return 1
        print(f"model        {model}")
        print(f"family       {image_pricing.image_model_family(model)}")
        print(f"config       {args.size} / {args.images} image(s) / "
              f"{args.inputs} input(s)")
        print(f"rate         ${est.output_rate:.3f} per image")
        print(f"output       ${est.output_cost:.4f}")
        print(f"input        ${est.input_cost:.4f}")
        print(f"price        ${est.amount:.4f}"
              f"{'  (estimated)' if est.is_estimate else ''}")
        if est.note:
            print(f"note         {est.note}")
        return 0

    if args.command == "recost":
        n = workflow.recost_all(conn)
        m = image_workflow.recost_all(conn)
        print(f"recosted {n} video task(s) at pricing version "
              f"{pricing.PRICING_VERSION}")
        print(f"recosted {m} image task(s) at pricing version "
              f"{image_pricing.IMAGE_PRICING_VERSION}")
        return 0

    if args.command == "price":
        if args.compare:
            print(f"{args.resolution} / {args.duration:g}s"
                  + (f" / {args.input_video_seconds:g}s video input"
                     if args.input_video_seconds else " / no video input"))
            for entry in models.summary():
                est = pricing.estimate_cost(
                    entry["family"], args.resolution, args.duration,
                    args.input_video_seconds,
                )
                if est.amount is None:
                    detail = est.note or "not supported"
                else:
                    rate = pricing.token_rate(
                        entry["family"], args.resolution,
                        bool(args.with_video or args.input_video_seconds))
                    detail = (f"${est.amount:.4f}"
                              + (f"   ${rate:.2f}/1M tok" if rate else ""))
                print(f"  {entry['family']:<20} {detail}")
            return 0

        try:
            model = models.resolve_model(args.model)
        except ValueError as exc:
            # Quoting only needs the family, not a dated model id, so fall back
            # to the family name and tell the user what to set for a real call.
            model = models.FAMILY_ALIASES.get((args.model or "").strip().lower(), args.model)
            print(f"note: {exc}", file=sys.stderr)
        has_video = args.with_video or bool(args.input_video_seconds)
        if args.tokens:
            est = pricing.cost_from_tokens(
                model, args.resolution, args.tokens, has_video)
        else:
            est = pricing.estimate_cost(
                model, args.resolution, args.duration, args.input_video_seconds,
            )
        if est.amount is None:
            print(f"no price: {est.note}", file=sys.stderr)
            return 1
        each = est.amount
        print(f"model        {model}")
        print(f"family       {pricing.model_family(model)}")
        print(f"config       {args.resolution} / {args.duration:g}s"
              + (f" / {args.input_video_seconds:g}s video input"
                 if args.input_video_seconds
                 else " / with video input" if has_video
                 else " / no video input"))
        rate = est.unit_price_per_million or pricing.token_rate(
            model, args.resolution, has_video)
        if rate:
            print(f"unit price   ${rate:.2f} per 1M tokens"
                  + ("  (with video input)" if has_video else ""))
        if args.tokens:
            print(f"tokens       {args.tokens:,}")
            print(f"price        ${each:.4f}"
                  f"   = ${rate:.2f} / 1,000,000 x {args.tokens:,}")
        else:
            print(f"projected    ${each:.4f}"
                  "   (final price is billed on actual token usage)")
        print(f"basis        {est.basis}")
        if est.note:
            print(f"note         {est.note}")
        return 0

    if args.command == "export":
        count = db.export_csv(conn, args.path)
        print(f"wrote {count} row(s) to {args.path}")
        return 0

    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
