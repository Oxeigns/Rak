"""Minimal Hugging Face Router decision API example.

Reads `HUGGINGFACE_TOKEN` from the environment and sends OpenAI-style messages
as a single `inputs` string payload.
"""

from __future__ import annotations

import os
from typing import Any

import requests

MODEL = "gpt-4o-mini"
API_URL = "https://router.huggingface.co/api/decision"


def call_router(messages: list[dict[str, str]], model: str = MODEL) -> dict[str, Any]:
    """Call the Router decision API and return the parsed JSON response."""
    hf_token = os.getenv("HUGGINGFACE_TOKEN")
    if not hf_token:
        raise RuntimeError("Missing HUGGINGFACE_TOKEN environment variable")

    headers = {
        "Authorization": f"Bearer {hf_token}",
        "Content-Type": "application/json",
    }

    prompt_text = "\n".join(message.get("content", "") for message in messages).strip()
    payload = {
        "model": model,
        "inputs": prompt_text,
    }

    response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def main() -> None:
    """Execute a single sample request."""
    messages = [{"role": "user", "content": "Hello World"}]
    print(call_router(messages))


if __name__ == "__main__":
    main()
