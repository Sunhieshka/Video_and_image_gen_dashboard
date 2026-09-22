"""Cost calculation for Ark video generation.

Prices are transcribed from the BytePlus Dreamina Seedance pricing tables
(USD, ap-southeast-1). PRICING_VERSION is stamped onto every row so a later
price change does not silently rewrite the cost history.

What the published tables give us:

  * no video input  - an exact per-video price at 5s output, plus a per-second
                      rate for other durations. Both are documented, so these
                      costs are exact (not estimates).
  * with video input - only the two endpoints of a range: the price for a short
                      input (2-4s, which the docs say is flat) and for the
                      longest supported input. The surcharge between them is
                      not linear through the origin, so anything in between is
                      interpolated and flagged is_estimate=True.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

PRICING_VERSION = "2026-09-22"
CURRENCY = "USD"

# Output duration the per-video and with-video table prices are quoted at.
REFERENCE_OUTPUT_SECONDS = 5


@dataclass(frozen=True)
class ResolutionPrice:
    """Published prices for one model + resolution."""

    per_second: float | None = None          # no video input, per output second
    per_video_ref: float | None = None       # no video input, 5s output, exact
    with_video_low: float | None = None      # 5s output, shortest input
    with_video_high: float | None = None     # 5s output, longest input
    input_low_seconds: float = 4.0           # low price covers inputs up to here
    input_high_seconds: float = 30.0         # high price is at this input length


def _p(per_second, per_video, lo=None, hi=None, in_lo=4.0, in_hi=30.0):
    return ResolutionPrice(per_second, per_video, lo, hi, in_lo, in_hi)


# family -> resolution -> prices. A missing resolution means "not supported".
PRICING: dict[str, dict[str, ResolutionPrice]] = {
    "seedance-2.5": {
        "480p":  _p(0.103, 0.514, 0.553, 2.152, 4.0, 30.0),
        "720p":  _p(0.231, 1.156, 1.244, 4.838, 4.0, 30.0),
        "1080p": _p(0.569, 2.843, 3.062, 11.907, 4.0, 30.0),
    },
    "seedance-2.0": {
        "480p":  _p(0.07, 0.35, 0.39, 0.86, 4.0, 15.0),
        "720p":  _p(0.15, 0.76, 0.84, 1.86, 4.0, 15.0),
        "1080p": _p(0.37, 1.87, 2.06, 4.57, 4.0, 15.0),
        "4k":    _p(0.78, 3.89, 4.20, 9.33, 4.0, 15.0),
    },
    "seedance-2.0-fast": {
        "480p": _p(0.06, 0.28, 0.30, 0.66, 4.0, 15.0),
        "720p": _p(0.12, 0.60, 0.64, 1.43, 4.0, 15.0),
    },
    "seedance-2.0-mini": {
        "480p": _p(0.04, 0.18, 0.19, 0.42, 4.0, 15.0),
        "720p": _p(0.08, 0.38, 0.41, 0.91, 4.0, 15.0),
    },
}

DEFAULT_RESOLUTION = "720p"

# ---------------------------------------------------------------------------
# Token pricing: the exact method.
#
#     price = unit_price / 1_000_000 * total_tokens
#
# USD per million tokens as (no video input, with video input). The with-video
# rate is lower because video input inflates the token count.
#
# This needs total_tokens, which the API only reports once a task finishes, so
# it is used for completed tasks. Quotes made before submitting fall back to
# the published per-video / per-second table above, flagged as estimates.
# ---------------------------------------------------------------------------

TOKEN_RATES: dict[str, dict[str, tuple[float, float]]] = {
    "seedance-2.5": {
        "480p":  (10.70, 6.40),
        "720p":  (10.70, 6.40),
        "1080p": (11.70, 7.00),
    },
    "seedance-2.0": {
        "480p":  (7.00, 4.30),
        "720p":  (7.00, 4.30),
        "1080p": (7.70, 4.70),
        "4k":    (4.00, 2.40),
    },
    "seedance-2.0-fast": {
        "480p": (5.60, 3.30),
        "720p": (5.60, 3.30),
    },
    "seedance-2.0-mini": {
        "480p": (3.50, 2.10),
        "720p": (3.50, 2.10),
    },
}

TOKENS_PER_UNIT = 1_000_000


def token_rate(
    model: str | None, resolution: str | None, has_video_input: bool = False
) -> float | None:
    """USD per million tokens for this model, resolution and input kind."""
    family = model_family(model)
    if family is None:
        return None
    res = normalize_resolution(resolution) or DEFAULT_RESOLUTION
    rates = TOKEN_RATES.get(family, {}).get(res)
    if rates is None:
        return None
    return rates[1] if has_video_input else rates[0]


def cost_from_tokens(
    model: str | None,
    resolution: str | None,
    total_tokens: int | float | None,
    has_video_input: bool = False,
) -> CostEstimate:
    """Exact cost: unit_price / 1_000_000 * total_tokens."""
    if not total_tokens:
        return CostEstimate(None, "no_token_usage", True, "total_tokens not reported")

    rate = token_rate(model, resolution, has_video_input)
    if rate is None:
        family = model_family(model)
        res = normalize_resolution(resolution)
        return CostEstimate(
            None, "no_token_rate", True,
            f"no token rate for {family or model!r} at {res or 'unknown resolution'}",
        )

    amount = rate / TOKENS_PER_UNIT * float(total_tokens)
    basis = "token_usage_with_video" if has_video_input else "token_usage"
    return CostEstimate(round(amount, 6), basis, False, None,
                        unit_price_per_million=rate)


# Columns as_row() owns. They are recomputed on every write, so they must be
# stored verbatim rather than COALESCEd -- see db.upsert_task(overwrite=...).
COST_COLUMNS = (
    "estimated_cost_usd", "cost_basis", "cost_is_estimate", "cost_currency",
    "pricing_version", "cost_note", "unit_price_per_million_usd",
)


@dataclass
class CostEstimate:
    amount: float | None
    basis: str                 # how it was computed
    is_estimate: bool
    note: str | None = None
    unit_price_per_million: float | None = None

    def as_row(self) -> dict[str, Any]:
        """Columns to merge into a video_tasks row."""
        return {
            "estimated_cost_usd": self.amount,
            "cost_basis": self.basis,
            "cost_is_estimate": int(self.is_estimate),
            "cost_currency": CURRENCY,
            "pricing_version": PRICING_VERSION,
            "cost_note": self.note,
            "unit_price_per_million_usd": self.unit_price_per_million,
        }


def model_family(model: str | None) -> str | None:
    """Map a model id such as dreamina-seedance-2-5-260628 to a price family."""
    if not model:
        return None
    m = model.lower().replace("_", "-")
    if "seedance-2-5" in m or "seedance-2.5" in m:
        return "seedance-2.5"
    if "seedance-2-0" in m or "seedance-2.0" in m:
        if "mini" in m:
            return "seedance-2.0-mini"
        if "fast" in m or "lite" in m:
            return "seedance-2.0-fast"
        return "seedance-2.0"
    return None


def normalize_resolution(resolution: str | None) -> str | None:
    if not resolution:
        return None
    r = str(resolution).strip().lower()
    aliases = {
        "480": "480p", "sd": "480p",
        "720": "720p", "hd": "720p",
        "1080": "1080p", "fhd": "1080p", "fullhd": "1080p",
        "2160p": "4k", "2160": "4k", "uhd": "4k",
    }
    return aliases.get(r, r)


def _surcharge(price: ResolutionPrice, input_seconds: float) -> tuple[float, bool, str | None]:
    """Video-input surcharge at the reference output duration."""
    assert price.per_video_ref is not None
    low = (price.with_video_low or price.per_video_ref) - price.per_video_ref
    high = (price.with_video_high or price.with_video_low or price.per_video_ref) - price.per_video_ref

    if input_seconds <= price.input_low_seconds:
        # The docs state this price is flat for short inputs, so it is exact.
        return low, False, None

    note = None
    clamped = input_seconds
    if input_seconds > price.input_high_seconds:
        clamped = price.input_high_seconds
        note = (
            f"input video {input_seconds:g}s exceeds the priced maximum of "
            f"{price.input_high_seconds:g}s; cost is a lower bound"
        )

    span = price.input_high_seconds - price.input_low_seconds
    frac = 0.0 if span <= 0 else (clamped - price.input_low_seconds) / span
    return low + frac * (high - low), True, note


def estimate_cost(
    model: str | None,
    resolution: str | None,
    duration_seconds: float | None,
    input_video_seconds: float | None = None,
) -> CostEstimate:
    """Cost for one generation.

    With video input the output cost scales with output duration and the
    video-input surcharge is added on top, interpolated on input length.
    """
    family = model_family(model)
    if family is None:
        return CostEstimate(None, "unknown_model", True, f"no price table for model {model!r}")

    assumed_resolution = not resolution
    res = normalize_resolution(resolution) or DEFAULT_RESOLUTION
    table = PRICING[family]
    price = table.get(res)
    if price is None:
        return CostEstimate(
            None, "unsupported_resolution", True,
            f"{family} has no published price for {res}",
        )

    if duration_seconds is None:
        return CostEstimate(None, "unknown_duration", True, "output duration missing")
    duration = float(duration_seconds)

    # Base cost, no video input.
    notes: list[str] = []
    is_estimate = False
    if duration == REFERENCE_OUTPUT_SECONDS and price.per_video_ref is not None:
        base = price.per_video_ref
        basis = "table_per_video"
    elif price.per_second is not None:
        base = price.per_second * duration
        basis = "table_per_second"
    else:
        return CostEstimate(None, "no_price", True, f"no rate for {family}/{res}")

    if assumed_resolution:
        notes.append(f"resolution unknown; assumed {res}")
        is_estimate = True

    if not input_video_seconds:
        return CostEstimate(
            round(base, 4), basis, is_estimate, "; ".join(notes) or None
        )

    # Video input: add the surcharge, which the tables quote at 5s output only.
    extra, extra_is_estimate, note = _surcharge(price, float(input_video_seconds))
    is_estimate = is_estimate or extra_is_estimate
    if note:
        notes.append(note)
    if duration != REFERENCE_OUTPUT_SECONDS:
        notes.append(
            f"video-input surcharge is published for {REFERENCE_OUTPUT_SECONDS}s output "
            f"only; applied unscaled to a {duration:g}s output"
        )
        is_estimate = True

    basis = "with_video_interpolated" if extra_is_estimate else "with_video_table"
    return CostEstimate(
        round(base + extra, 4), basis, is_estimate, "; ".join(notes) or None
    )


def row_has_video_input(row: Mapping[str, Any]) -> bool:
    """Did this request include video input? It selects the token rate."""
    flag = row.get("has_video_input")
    if flag is not None:
        return bool(flag)
    return bool(row.get("input_video_seconds"))


def cost_for_row(row: Mapping[str, Any]) -> CostEstimate:
    """Cost for a stored (or freshly flattened) task row.

    Once the API reports token usage the price is exact:
    unit_price / 1_000_000 * total_tokens. Before that -- a queued or running
    task -- fall back to the published per-video table so the UI can still show
    a projected cost, flagged as an estimate.
    """
    status = (row.get("status") or "").lower()
    if status in ("failed", "cancelled"):
        return CostEstimate(0.0, f"not_billed_{status}", False, None)

    model = row.get("model")
    resolution = row.get("resolution") or row.get("requested_resolution")
    has_video = row_has_video_input(row)

    exact = cost_from_tokens(model, resolution, row.get("total_tokens"), has_video)
    if exact.amount is not None:
        return exact

    duration = row.get("duration") or row.get("requested_duration")
    fallback = estimate_cost(model, resolution, duration,
                             row.get("input_video_seconds"))
    if fallback.amount is not None:
        note = "projected from the published table; token usage not reported yet"
        fallback = CostEstimate(
            fallback.amount, fallback.basis, True,
            "; ".join(filter(None, [fallback.note, note])),
            fallback.unit_price_per_million,
        )
    return fallback
