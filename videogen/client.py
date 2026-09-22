"""Thin wrapper over the BytePlus Ark runtime SDK."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from .errors import translate

DEFAULT_BASE_URL = os.environ.get(
    "ARK_BASE_URL", "https://ark.ap-southeast.bytepluses.com/api/v3"
)
DEFAULT_MODEL = os.environ.get("ARK_VIDEO_MODEL", "dreamina-seedance-2-5-260628")
DEFAULT_IMAGE_MODEL = os.environ.get(
    "ARK_IMAGE_MODEL", "dola-seedream-5-0-pro-260628")


def _import_ark():
    # The package has shipped under two import names.
    try:
        from byteplussdkarkruntime import Ark  # type: ignore
        return Ark
    except ImportError:
        pass
    try:
        from arkruntime import Ark  # type: ignore
        return Ark
    except ImportError as exc:  # pragma: no cover - surfaced to the user
        raise ImportError(
            "Ark SDK not installed. Run: pip install byteplussdkarkruntime"
        ) from exc


def make_client(api_key: str | None = None, base_url: str | None = None):
    api_key = api_key or os.environ.get("ARK_API_KEY")
    if not api_key:
        raise RuntimeError("ARK_API_KEY is not set")
    Ark = _import_ark()
    return Ark(base_url=base_url or DEFAULT_BASE_URL, api_key=api_key)


# Content part types the SDK accepts, with the role each defaults to.
# Confirmed against CreateTaskContentParam in byteplussdkarkruntime.
DEFAULT_ROLES: dict[str, str] = {
    "image_url": "reference_image",
    "video_url": "reference_video",
    "audio_url": "reference_audio",
}


def build_content(
    prompt: str, references: Sequence[Mapping[str, Any]] = ()
) -> list[dict[str, Any]]:
    """Build the `content` array: the text prompt plus reference media.

    Each reference is {"type": "image_url"|"video_url"|"audio_url",
    "url": ..., "role": ...}.
    """
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for ref in references:
        ref_type = ref.get("type") or ref.get("ref_type")
        url = ref["url"]
        if ref_type not in DEFAULT_ROLES:
            raise ValueError(
                f"unsupported reference type: {ref_type!r}; "
                f"expected one of {', '.join(sorted(DEFAULT_ROLES))}"
            )
        content.append({
            "type": ref_type,
            ref_type: {"url": url},
            "role": ref.get("role") or DEFAULT_ROLES[ref_type],
        })
    return content


def create_task(client, **kwargs) -> Any:
    try:
        return client.content_generation.tasks.create(**kwargs)
    except Exception as exc:
        raise translate(exc) from exc


def get_task(client, task_id: str) -> Any:
    try:
        return client.content_generation.tasks.get(task_id=task_id)
    except Exception as exc:
        raise translate(exc) from exc


def generate_image(client, **kwargs) -> Any:
    """Synchronous image generation: the response carries the images."""
    try:
        return client.images.generate(**kwargs)
    except Exception as exc:
        raise translate(exc) from exc
