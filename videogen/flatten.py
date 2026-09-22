"""Turn an Ark task response into a flat {column: value} dict.

The API returns a few nested objects (content, usage, error); everything else
is already scalar. Nested scalars are flattened to `parent_child` names, and
any field we have not modelled still becomes its own column via
db.ensure_columns, so new API parameters show up without a code change.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

# Nested objects whose scalar children are hoisted into top-level columns.
# content.video_url -> video_url, usage.total_tokens -> total_tokens,
# error.code -> error_code, error.message -> error_message.
_HOIST = {
    "content": "",        # no prefix
    "usage": "",          # no prefix
    "error": "error_",
}

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


def to_dict(obj: Any) -> dict[str, Any]:
    """Best-effort conversion of an SDK response object to a plain dict."""
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                result = fn()
            except TypeError:
                continue
            if isinstance(result, Mapping):
                return dict(result)
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return {"value": obj}


def _scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (str, int, float)) or value is None:
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def flatten_task(response: Any) -> dict[str, Any]:
    """Flatten a tasks.create / tasks.get response into one row of columns."""
    data = to_dict(response)
    row: dict[str, Any] = {}

    for key, value in data.items():
        if key in _HOIST:
            # A null nested object (the usual case for `error` on success) has
            # nothing to hoist. Skip it rather than creating a raw column that
            # shadows the flattened error_code / error_message ones.
            if value is None:
                continue
            prefix = _HOIST[key]
            nested = to_dict(value)
            if not nested and not isinstance(value, Mapping):
                row[key] = _scalar(value)
                continue
            for nkey, nvalue in nested.items():
                row[f"{prefix}{nkey}"] = _scalar(nvalue)
            continue
        row[key] = _scalar(value)

    row["raw_response"] = json.dumps(data, ensure_ascii=False, default=str)
    return row


def extract_references(content: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Pull the reference image/video entries out of a request content array."""
    refs: list[dict[str, Any]] = []
    for part in content:
        ptype = part.get("type")
        if ptype not in ("image_url", "video_url", "audio_url"):
            continue
        url = (part.get(ptype) or {}).get("url")
        refs.append({"ref_type": ptype, "role": part.get("role"), "url": url})
    return refs


def extract_prompt(content: list[Mapping[str, Any]]) -> str | None:
    texts = [p.get("text") for p in content if p.get("type") == "text" and p.get("text")]
    return "\n".join(texts) if texts else None


def is_terminal(status: str | None) -> bool:
    return (status or "").lower() in TERMINAL_STATUSES
