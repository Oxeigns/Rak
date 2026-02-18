"""OpenAI -> Hugging Face Router Python converter.

Usage:
    python utils/openai_to_hf_router_converter.py path/to/input.py [-o path/to/output.py]

This utility performs a structure-preserving conversion of common OpenAI Python API
patterns into Hugging Face Router API calls while keeping surrounding functions,
loops, and variables intact.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

INSTALL_GUIDE = '''# Required installation
# pip install huggingface_hub requests transformers
#
# Environment variable setup:
# export HUGGINGFACE_TOKEN="hf_xxxxxYOURKEYxxxxx"
#
# Heroku:
# heroku config:set HUGGINGFACE_TOKEN=hf_xxxxxYOURKEYxxxxx
'''


def _ensure_imports(code: str) -> str:
    """Ensure os and requests are imported and remove openai import."""
    code = re.sub(r"^\s*import\s+openai\s*\n", "", code, flags=re.MULTILINE)
    if "import os" not in code:
        code = "import os\n" + code
    if "import requests" not in code:
        code = "import requests\n" + code
    return code


def _replace_api_key(code: str) -> str:
    """Replace OpenAI API key usage with Hugging Face token environment variable."""
    # openai.api_key = "..."
    code = re.sub(
        r"^\s*openai\.api_key\s*=.*$",
        'HF_TOKEN = os.getenv("HUGGINGFACE_TOKEN")  # replaced OpenAI key',
        code,
        flags=re.MULTILINE,
    )

    # OPENAI_KEY var references
    code = code.replace("OPENAI_KEY", "HUGGINGFACE_TOKEN")

    # If no explicit token line exists, add one.
    if 'HF_TOKEN = os.getenv("HUGGINGFACE_TOKEN")' not in code:
        code = 'HF_TOKEN = os.getenv("HUGGINGFACE_TOKEN")\n' + code

    return code


def _replace_endpoint(code: str) -> str:
    """Replace old Hugging Face endpoint with new Router endpoint."""
    return code.replace(
        "https://api-inference.huggingface.co",
        "https://router.huggingface.co/api/decision",
    )


def _messages_to_inputs(code: str) -> str:
    """Convert OpenAI message arrays into joined inputs strings in payloads."""
    # Convert simple literal messages=[{...}] into inputs="..."
    literal_pattern = re.compile(
        r"messages\s*=\s*\[\s*\{\s*['\"]role['\"]\s*:\s*['\"](?:user|system|assistant)['\"]\s*,\s*['\"]content['\"]\s*:\s*(['\"][\s\S]*?['\"])\s*\}\s*\]",
        re.MULTILINE,
    )
    code = literal_pattern.sub(r"inputs=\1", code)

    # Convert dict payload style: "messages": messages_var -> "inputs": "\n".join(...)
    code = re.sub(
        r"(['\"]?)messages\1\s*:\s*([a-zA-Z_][a-zA-Z0-9_]*)",
        r'"inputs": "\\n".join([m.get("content", "") for m in \2])',
        code,
    )

    return code


def _replace_chat_completion_call(code: str) -> str:
    """Replace OpenAI ChatCompletion call with requests.post router call."""
    code = re.sub(
        r"openai\.ChatCompletion\.create\(",
        "requests.post(\n    API_URL,\n    headers=headers,\n    json={",
        code,
    )
    code = re.sub(
        r"client\.chat\.completions\.create\(",
        "requests.post(\n    API_URL,\n    headers=headers,\n    json={",
        code,
    )

    # Replace model mappings
    code = re.sub(r"model\s*=\s*['\"]gpt-4['\"]", '"model": "gpt-4o-mini"', code)
    code = re.sub(r"model\s*=\s*['\"]gpt-3\.5[^'\"]*['\"]", '"model": "gpt2"', code)

    # Ensure request config variables exist when requests.post conversion happened
    if "requests.post(" in code:
        prelude = (
            'API_URL = "https://router.huggingface.co/api/decision"  # new router endpoint\n'
            'headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}\n'
        )
        if "API_URL = " not in code:
            code = prelude + code

    return code


def _replace_response_parsing(code: str) -> str:
    """Replace common OpenAI response field access with JSON parsing from requests."""
    code = code.replace(
        "response.choices[0].message.content",
        'response.json().get("generated_text") or response.json().get("output", "")',
    )
    return code


def convert_openai_to_hf_router(code: str) -> str:
    """Run all conversion passes and prepend installation/env instructions."""
    converted = code
    converted = _ensure_imports(converted)
    converted = _replace_api_key(converted)
    converted = _replace_endpoint(converted)
    converted = _replace_chat_completion_call(converted)
    converted = _messages_to_inputs(converted)
    converted = _replace_response_parsing(converted)

    # Inject canonical headers if legacy authorization string remains
    converted = converted.replace(
        'headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}',
        'headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}',
    )

    # Keep runnable by closing converted json payload call if needed
    converted = converted.replace(
        ")\nprint(response.json().get(\"generated_text\") or response.json().get(\"output\", \"\"))",
        "})\nprint(response.json().get(\"generated_text\") or response.json().get(\"output\", \"\"))",
    )

    return INSTALL_GUIDE + "\n" + converted


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert OpenAI Python code to Hugging Face Router API code")
    parser.add_argument("input", type=Path, help="Path to input Python file")
    parser.add_argument("-o", "--output", type=Path, help="Path to write converted Python file")
    args = parser.parse_args()

    source = args.input.read_text(encoding="utf-8")
    converted = convert_openai_to_hf_router(source)

    output_path = args.output or args.input.with_name(f"{args.input.stem}_hf_router.py")
    output_path.write_text(converted, encoding="utf-8")
    print(f"Converted file written to: {output_path}")


if __name__ == "__main__":
    main()
