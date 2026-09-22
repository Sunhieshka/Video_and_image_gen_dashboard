"""Cost calculation for Ark image generation.

Images are priced per image, not per token:

    price = output_rate(model, pixels) x generated_images
          + input_rate(model) x billable_input_images

For seedream-5.0-pro the output rate is tiered on the pixel count of the image
actually produced (the response reports it as e.g. "1760x2368"), and input
images are free for the first one then charged per image. The other models are
a flat rate with free input.

Layer decomposition is deliberately not priced here -- it is a separate rate
card and this project does not use it. A request that asks for it is flagged
rather than silently costed at the single-image rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

IMAGE_PRICING_VERSION = "2026-09-22"
CURRENCY = "USD"

# "1.5K or lower" in the published table.
PIXEL_TIER = 2_610_000

# The API takes size presets and resolves them to real dimensions (a 2K request
# came back as 1760x2368). These are representative pixel counts so a quote
# made before the request lands on the right tier; the exact dimensions vary
# with aspect ratio, but each preset sits well clear of the tier boundary.
SIZE_PRESETS: dict[str, int] = {
    "1k": 1024 * 1024,          # ~1.0M  -> small tier
    "1.5k": 1536 * 1536,        # ~2.4M  -> small tier (the "1.5K or lower" row)
    "2k": 1760 * 2368,          # ~4.2M  -> large tier
    "4k": 3840 * 2160,          # ~8.3M  -> large tier
}


@dataclass(frozen=True)
class ImagePrice:
    """Published prices for one image model, USD per image."""

    output_small: float               # <= PIXEL_TIER pixels
    output_large: float               # > PIXEL_TIER pixels
    input_per_image: float = 0.0      # charged per billable input image
    input_free_count: int = 0         # this many input images cost nothing
    model_id: str | None = None
    sizes: tuple[str, ...] = ()       # sizes the model accepts

    def output_rate(self, pixels: int | None) -> float:
        # With no reported size, assume the larger tier rather than quietly
        # under-reporting the bill.
        if pixels is None:
            return self.output_large
        return self.output_small if pixels <= PIXEL_TIER else self.output_large


IMAGE_PRICING: dict[str, ImagePrice] = {
    "seedream-5.0-pro": ImagePrice(
        output_small=0.045, output_large=0.09,
        input_per_image=0.003, input_free_count=1,
        model_id="dola-seedream-5-0-pro-260628",
        sizes=("1K", "1.5K", "2K"),
    ),
    "seedream-5.0": ImagePrice(
        output_small=0.035, output_large=0.035,
        model_id="seedream-5-0-260128",
        sizes=("2K", "4K"),
    ),
    "seedream-4.5": ImagePrice(
        output_small=0.04, output_large=0.04,
        model_id="seedream-4-5-251128",
        sizes=("2K", "4K"),
    ),
}

DEFAULT_IMAGE_FAMILY = "seedream-5.0-pro"


@dataclass
class ImageCost:
    amount: float | None
    basis: str
    is_estimate: bool
    note: str | None = None
    output_rate: float | None = None
    output_cost: float | None = None
    input_cost: float | None = None

    def as_row(self) -> dict[str, Any]:
        return {
            "estimated_cost_usd": self.amount,
            "cost_basis": self.basis,
            "cost_is_estimate": int(self.is_estimate),
            "cost_currency": CURRENCY,
            "pricing_version": IMAGE_PRICING_VERSION,
            "cost_note": self.note,
            "output_rate_usd": self.output_rate,
            "output_cost_usd": self.output_cost,
            "input_cost_usd": self.input_cost,
        }


def image_model_family(model: str | None) -> str | None:
    """Map a model id such as dola-seedream-5-0-pro-260628 to a price family.

    The plain 5.0 id carries no variant word (`seedream-5-0-260128`), so it is
    the fallback for the 5.0 line once pro is ruled out. `lite` maps there too:
    the pricing table lists it at the same rate.
    """
    if not model:
        return None
    m = model.lower().replace("_", "-").replace(".", "-")
    if "seedream-4-5" in m:
        return "seedream-4.5"
    if "seedream-5" in m:
        if "pro" in m:
            return "seedream-5.0-pro"
        if "flash" in m:
            # Flash is a real model at its own rate, but it is not in use here
            # and is not priced. Return unknown rather than letting it fall
            # through to the base 5.0 rate and be billed at the wrong price.
            return None
        return "seedream-5.0"
    return None


def parse_pixels(size: str | None) -> int | None:
    """Pixel count from a size string like '1760x2368'.

    Presets such as '2K' cannot be resolved to a pixel count until the API
    reports the real dimensions, so they return None.
    """
    if not size:
        return None
    text = str(size).strip().lower().replace("*", "x").replace("×", "x")
    if text in SIZE_PRESETS:
        return SIZE_PRESETS[text]
    if "x" not in text:
        return None
    width, _, height = text.partition("x")
    try:
        return int(float(width)) * int(float(height))
    except ValueError:
        return None


def estimate_image_cost(
    model: str | None,
    *,
    sizes: Sequence[str | None] | None = None,
    generated_images: int | None = None,
    input_images: int = 0,
    layer_decomposition: bool = False,
) -> ImageCost:
    """Cost for one image generation request.

    `sizes` are the dimensions of the images produced, one per image, which is
    what the tiered pro rate is keyed on. When they are not known yet -- a
    quote before the request runs -- pass none and the larger tier is assumed.
    """
    family = image_model_family(model)
    if family is None:
        return ImageCost(None, "unknown_model", True,
                         f"no price table for image model {model!r}")

    price = IMAGE_PRICING[family]
    notes: list[str] = []
    is_estimate = False

    size_list = list(sizes or [])
    count = generated_images if generated_images is not None else len(size_list)
    if not count:
        count = 1
        is_estimate = True
        notes.append("image count unknown; assumed 1")

    # Pad or trim so every produced image gets a rate.
    while len(size_list) < count:
        size_list.append(size_list[-1] if size_list else None)
    size_list = size_list[:count]

    output_cost = 0.0
    rates: list[float] = []
    for size in size_list:
        pixels = parse_pixels(size)
        if pixels is None and price.output_small != price.output_large:
            is_estimate = True
            notes.append(
                f"output size unknown; assumed the >{PIXEL_TIER / 1e6:g}M pixel "
                f"tier (${price.output_large:.3f})"
            )
        rate = price.output_rate(pixels)
        rates.append(rate)
        output_cost += rate

    billable_inputs = max(0, int(input_images) - price.input_free_count)
    input_cost = billable_inputs * price.input_per_image

    if layer_decomposition:
        is_estimate = True
        notes.append(
            "layer decomposition is not priced here; this is the "
            "single-image-generation rate only"
        )

    total = round(output_cost + input_cost, 6)
    basis = "image_table_estimated" if is_estimate else "image_table"
    # De-duplicate: one note per distinct reason, not one per image.
    seen: list[str] = []
    for note in notes:
        if note not in seen:
            seen.append(note)

    return ImageCost(
        total, basis, is_estimate, "; ".join(seen) or None,
        output_rate=rates[0] if rates else None,
        output_cost=round(output_cost, 6),
        input_cost=round(input_cost, 6),
    )


def cost_for_image_row(
    row: Mapping[str, Any], sizes: Sequence[str | None] | None = None
) -> ImageCost:
    """Cost for a stored (or freshly flattened) image task row."""
    if row.get("error_code") or (row.get("status") or "").lower() == "failed":
        return ImageCost(0.0, "not_billed_failed", False, None)

    return estimate_image_cost(
        row.get("model"),
        sizes=sizes,
        generated_images=row.get("generated_images"),
        input_images=row.get("input_images") or 0,
        layer_decomposition=bool(row.get("layer_decomposition")),
    )


def supported_sizes(model: str | None) -> tuple[str, ...]:
    """Sizes this model accepts. Empty when the model is unknown."""
    family = image_model_family(model)
    if family is None:
        return ()
    return IMAGE_PRICING[family].sizes


def normalize_size(size: str | None) -> str | None:
    """Canonical spelling of a size preset: '1.5k' -> '1.5K'."""
    if not size:
        return None
    text = str(size).strip().lower()
    canonical = {"1k": "1K", "1.5k": "1.5K", "2k": "2K", "4k": "4K"}
    return canonical.get(text, str(size).strip())


def validate_image_request(
    model: str | None, size: str | None = None
) -> tuple[list[str], list[str]]:
    """Check a request against what the model supports.

    Returns (errors, warnings). The models accept different size sets -- pro
    tops out at 2K while 5.0 and 4.5 start there -- so a bad pairing is caught
    before it costs anything.
    """
    errors: list[str] = []
    warnings: list[str] = []

    family = image_model_family(model)
    if family is None:
        warnings.append(
            f"unrecognised image model {model!r}: sent as-is, and the cost "
            "cannot be calculated"
        )
        return errors, warnings

    sizes = IMAGE_PRICING[family].sizes
    if size and sizes:
        wanted = normalize_size(size)
        # An explicit WxH is passed through; only presets are checked.
        if wanted and wanted.lower().endswith("k") and wanted not in sizes:
            errors.append(
                f"{family} does not support {wanted}; supported: {', '.join(sizes)}"
            )

    return errors, warnings
