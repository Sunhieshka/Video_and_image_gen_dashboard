"""Model registry: aliases, capabilities, and pre-flight validation.

Seedance ships as four priced variants — 2.5, 2.0, 2.0 Fast and 2.0 Mini — and
they do not accept the same requests. Fast and Mini top out at 720p, only 2.0
offers 4K, and the video-input length ceiling differs (30s on 2.5, 15s on the
2.0 series). Validating here means a bad combination fails before it costs
anything, rather than being rejected by the API mid-batch.

Capabilities are derived from the published pricing tables wherever possible,
so there is one source of truth: if a resolution has a price, the model
supports it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from . import pricing

# Aliases so you can say `--model mini` instead of pasting a full id.
FAMILY_ALIASES: dict[str, str] = {
    "2.5": "seedance-2.5", "2-5": "seedance-2.5", "25": "seedance-2.5",
    "seedance-2.5": "seedance-2.5", "seedance2.5": "seedance-2.5",
    "2.0": "seedance-2.0", "2-0": "seedance-2.0", "20": "seedance-2.0",
    "seedance-2.0": "seedance-2.0", "seedance2.0": "seedance-2.0",
    "fast": "seedance-2.0-fast", "2.0-fast": "seedance-2.0-fast",
    "seedance-2.0-fast": "seedance-2.0-fast",
    "mini": "seedance-2.0-mini", "2.0-mini": "seedance-2.0-mini",
    "seedance-2.0-mini": "seedance-2.0-mini",
}

# Concrete model ids. Only the two that appear in the BytePlus docs are filled
# in; Fast and Mini carry their own dated ids, so set them via the environment
# (ARK_MODEL_SEEDANCE_2_0_FAST / ..._MINI) or pass the full id to --model.
_KNOWN_MODEL_IDS: dict[str, str | None] = {
    "seedance-2.5": "dreamina-seedance-2-5-260628",
    "seedance-2.0": "dreamina-seedance-2-0-260128",
    "seedance-2.0-fast": None,
    "seedance-2.0-mini": None,
}

_ENV_KEYS = {
    "seedance-2.5": "ARK_MODEL_SEEDANCE_2_5",
    "seedance-2.0": "ARK_MODEL_SEEDANCE_2_0",
    "seedance-2.0-fast": "ARK_MODEL_SEEDANCE_2_0_FAST",
    "seedance-2.0-mini": "ARK_MODEL_SEEDANCE_2_0_MINI",
}

# Whether the family accepts 2.5's omni-reference parameters. Only 2.5 is
# documented as supporting them; None means "not verified", which warns rather
# than blocking so an undocumented capability is not hard-refused.
_OMNI_REFERENCE: dict[str, bool | None] = {
    "seedance-2.5": True,
    "seedance-2.0": None,
    "seedance-2.0-fast": None,
    "seedance-2.0-mini": None,
}

DEFAULT_FAMILY = "seedance-2.5"


def default_model() -> str:
    """The model used when none is given. ARK_VIDEO_MODEL still wins."""
    override = os.environ.get("ARK_VIDEO_MODEL")
    if override:
        return override
    return model_id_for(DEFAULT_FAMILY)


def model_id_for(family: str) -> str:
    """Concrete model id for a family, honouring environment overrides."""
    env_key = _ENV_KEYS.get(family)
    if env_key and os.environ.get(env_key):
        return os.environ[env_key]
    model_id = _KNOWN_MODEL_IDS.get(family)
    if model_id:
        return model_id
    raise ValueError(
        f"no model id known for {family}. BytePlus versions these ids by date, "
        f"so set {env_key} or pass the full id to --model "
        f"(e.g. --model dreamina-{family.replace('.', '-')}-XXXXXX)."
    )


def resolve_model(spec: str | None) -> str:
    """Turn an alias or a full model id into a model id.

    'mini' -> the Mini model id; anything unrecognised is passed through
    untouched so a brand new model id still works without a code change.
    """
    if not spec:
        return default_model()
    key = spec.strip().lower()
    if key in FAMILY_ALIASES:
        return model_id_for(FAMILY_ALIASES[key])
    return spec


@dataclass
class Capabilities:
    family: str
    resolutions: tuple[str, ...]
    input_video_max_seconds: float | None
    input_video_flat_until_seconds: float | None
    omni_reference: bool | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "resolutions": list(self.resolutions),
            "input_video_max_seconds": self.input_video_max_seconds,
            "omni_reference": self.omni_reference,
        }


_RES_ORDER = ["480p", "720p", "1080p", "4k"]


def capabilities(model: str | None) -> Capabilities | None:
    """What a model supports, derived from the price table."""
    family = pricing.model_family(model)
    if family is None:
        return None
    table = pricing.PRICING[family]
    resolutions = tuple(sorted(table, key=lambda r: _RES_ORDER.index(r)
                               if r in _RES_ORDER else 99))
    any_price = next(iter(table.values()))
    return Capabilities(
        family=family,
        resolutions=resolutions,
        input_video_max_seconds=any_price.input_high_seconds,
        input_video_flat_until_seconds=any_price.input_low_seconds,
        omni_reference=_OMNI_REFERENCE.get(family),
    )


def validate_request(
    model: str | None,
    resolution: str | None = None,
    duration: float | None = None,
    input_video_seconds: float | None = None,
    omni_reference_task_type: str | None = None,
    reference_video_count: int = 0,
) -> tuple[list[str], list[str]]:
    """Check a request against the model's capabilities.

    Returns (errors, warnings). Errors are combinations the model has no
    published support for; warnings are things worth knowing that should not
    block a request.
    """
    errors: list[str] = []
    warnings: list[str] = []

    caps = capabilities(model)
    if caps is None:
        warnings.append(
            f"unrecognised model {model!r}: capabilities and pricing unknown, "
            "so the request is sent as-is and cost will not be calculated"
        )
        return errors, warnings

    if resolution:
        res = pricing.normalize_resolution(resolution)
        if res not in caps.resolutions:
            errors.append(
                f"{caps.family} does not support {res}; "
                f"supported: {', '.join(caps.resolutions)}"
            )

    if duration is not None and duration <= 0:
        errors.append(f"duration must be positive, got {duration}")

    if input_video_seconds and caps.input_video_max_seconds:
        if input_video_seconds > caps.input_video_max_seconds:
            warnings.append(
                f"{input_video_seconds:g}s of video input exceeds the "
                f"{caps.input_video_max_seconds:g}s that {caps.family} publishes "
                "a price for; the request may be rejected and the cost is a "
                "lower bound"
            )

    if omni_reference_task_type:
        if caps.omni_reference is False:
            errors.append(f"{caps.family} does not support omni_reference_task_type")
        elif caps.omni_reference is None:
            warnings.append(
                f"omni_reference_task_type is documented for seedance-2.5; "
                f"support on {caps.family} is unverified"
            )

    if reference_video_count and caps.family != "seedance-2.5":
        warnings.append(
            f"{reference_video_count} reference video(s) on {caps.family}: "
            "multi-video reference is documented for seedance-2.5"
        )

    return errors, warnings


def summary() -> list[dict[str, Any]]:
    """Every family with its capabilities and headline prices, for `models`."""
    out: list[dict[str, Any]] = []
    for family in pricing.PRICING:
        table = pricing.PRICING[family]
        try:
            model_id: str | None = model_id_for(family)
        except ValueError:
            model_id = None
        caps = Capabilities(
            family=family,
            resolutions=tuple(sorted(table, key=lambda r: _RES_ORDER.index(r)
                                     if r in _RES_ORDER else 99)),
            input_video_max_seconds=next(iter(table.values())).input_high_seconds,
            input_video_flat_until_seconds=next(iter(table.values())).input_low_seconds,
            omni_reference=_OMNI_REFERENCE.get(family),
        )
        out.append({
            "family": family,
            "model_id": model_id,
            "aliases": sorted(k for k, v in FAMILY_ALIASES.items() if v == family),
            "capabilities": caps,
            "prices": {res: table[res] for res in caps.resolutions},
        })
    return out
