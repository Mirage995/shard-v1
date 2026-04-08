"""vlm_ingestion.py -- Minimal visual ingestion adapter for SHARD.

Converts images into structured text that can be appended to ctx.raw_text
and later stored in ChromaDB through the existing text-first pipeline.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_VLM_MODEL", "qwen2.5vl:3b")

OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_VLM_MODEL",
    "qwen/qwen-2.5-vl-7b-instruct:free",
)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_REFERER = os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost")
OPENROUTER_TITLE = os.getenv("OPENROUTER_X_TITLE", "SHARD Visual Ingestion")

REQUEST_TIMEOUT_SEC = float(os.getenv("VLM_REQUEST_TIMEOUT_SEC", "30"))
OPENROUTER_RETRIES = int(os.getenv("OPENROUTER_RETRIES", "2"))


def _guess_media_type(image_path: str) -> str:
    media_type, _ = mimetypes.guess_type(image_path)
    return media_type or "image/png"


def _read_image_b64(image_path: str) -> str:
    data = Path(image_path).read_bytes()
    return base64.b64encode(data).decode("ascii")


def _build_prompt(topic: str) -> str:
    return (
        f"You are extracting visual evidence for the SHARD study topic: '{topic}'.\n"
        "Describe ONLY what is visually grounded in the image.\n"
        "Return plain text with exactly these sections:\n"
        "Objects/Entities:\n"
        "Readable Text:\n"
        "Spatial Relations:\n"
        "Meaning Relative To Topic:\n"
        "Uncertainties:\n"
        "Rules:\n"
        "- Be concrete, not generic.\n"
        "- If text is unreadable, say 'none confidently read'.\n"
        "- If the image is a chart, diagram, molecule, or paper figure, name that explicitly.\n"
        "- State uncertainty explicitly instead of guessing.\n"
        "- Keep the answer compact but specific.\n"
    )


def _post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _call_ollama(image_path: str, topic: str) -> tuple[str, str]:
    image_b64 = _read_image_b64(image_path)
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": _build_prompt(topic),
                "images": [image_b64],
            }
        ],
    }
    data = _post_json(OLLAMA_URL, payload)
    content = data.get("message", {}).get("content", "").strip()
    if not content:
        raise ValueError("Empty Ollama VLM response")
    return content, f"ollama:{OLLAMA_MODEL}"


def _call_openrouter(image_path: str, topic: str) -> tuple[str, str]:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not configured")

    image_b64 = _read_image_b64(image_path)
    media_type = _guess_media_type(image_path)
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _build_prompt(topic)},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_b64}",
                        },
                    },
                ],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": OPENROUTER_REFERER,
        "X-Title": OPENROUTER_TITLE,
    }
    last_exc: Exception | None = None
    for attempt in range(1, OPENROUTER_RETRIES + 1):
        try:
            data = _post_json(OPENROUTER_URL, payload, headers=headers)
            choices = data.get("choices") or []
            if not choices:
                raise ValueError("Empty OpenRouter VLM response")
            content = choices[0].get("message", {}).get("content", "").strip()
            if not content:
                raise ValueError("Empty OpenRouter content")
            return content, f"openrouter:{OPENROUTER_MODEL}"
        except Exception as exc:
            last_exc = exc
            if attempt == OPENROUTER_RETRIES:
                raise
    raise last_exc  # pragma: no cover


def _describe_single_image(image_path: str, topic: str) -> tuple[str, str]:
    try:
        return _call_openrouter(image_path, topic)
    except Exception:
        return _call_ollama(image_path, topic)


def describe_images(image_paths: list[str], topic: str) -> str:
    """Describe images and return a text block ready for ctx.raw_text append."""
    if not image_paths:
        return ""

    blocks: list[str] = ["[VISUAL EVIDENCE]"]
    for idx, image_path in enumerate(image_paths, start=1):
        try:
            description, provider = _describe_single_image(image_path, topic)
            error_flag = "false"
        except Exception as exc:
            description = (
                "Objects/Entities:\nanalysis unavailable\n"
                "Readable Text:\nnone confidently read\n"
                "Spatial Relations:\nunknown\n"
                "Meaning Relative To Topic:\ninsufficient evidence due to provider failure\n"
                f"Uncertainties:\nprovider error: {type(exc).__name__}"
            )
            provider = "unavailable"
            error_flag = "true"

        blocks.append(
            "\n".join(
                [
                    f"Image {idx} ({image_path}):",
                    "source: visual_ingestion",
                    f"image_path: {image_path}",
                    f"provider: {provider}",
                    f"error: {error_flag}",
                    description.strip(),
                ]
            )
        )

    return "\n\n".join(blocks).strip()
