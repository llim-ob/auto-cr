#!/usr/bin/env python3
"""Teamwork OAuth and Qwen API helpers."""

import json
import base64
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

CLIENT_ID = os.getenv("TW_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("TW_CLIENT_SECRET", "")
API_KEY = os.getenv("TW_API_KEY", "")
ACCESS_TOKEN = os.getenv("TW_ACCESS_TOKEN", "")
AUTH_CODE = os.getenv("TW_AUTH_CODE", "")
REDIRECT_URI = os.getenv("TW_REDIRECT_URI", "")
BASE_URL = "https://objectbright.teamwork.com"

QWEN_API_BASE = os.getenv("QWEN_API_BASE", "https://gpu.ltcglobal.com/v1").rstrip("/")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-mtp-35b")
QWEN_CONNECT_TIMEOUT = float(os.getenv("QWEN_CONNECT_TIMEOUT", "15"))
QWEN_READ_TIMEOUT = float(os.getenv("QWEN_READ_TIMEOUT", "180"))
QWEN_MAX_TOKENS = int(os.getenv("QWEN_MAX_TOKENS", "128"))


def get_token() -> str:
    """Return stored token, or exchange a one-time Developer Portal auth code."""
    if ACCESS_TOKEN:
        return ACCESS_TOKEN
    if not CLIENT_ID or not CLIENT_SECRET or not AUTH_CODE or not REDIRECT_URI:
        raise RuntimeError(
            "Set TW_ACCESS_TOKEN, or set TW_CLIENT_ID, TW_CLIENT_SECRET, "
            "TW_AUTH_CODE, and TW_REDIRECT_URI for the initial OAuth exchange"
        )

    resp = requests.post(
        "https://www.teamwork.com/launchpad/v1/token.json",
        json={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": AUTH_CODE,
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    try:
        return resp.json()["access_token"]
    except (KeyError, ValueError) as exc:
        raise RuntimeError("Teamwork OAuth response did not contain an access token") from exc


def get_auth_headers() -> dict[str, str]:
    """Build Teamwork auth headers for an API key or OAuth access token."""
    if API_KEY:
        encoded = base64.b64encode(f"{API_KEY}:".encode()).decode()
        return {"Authorization": f"Basic {encoded}", "Accept": "application/json"}
    if ACCESS_TOKEN:
        return {"Authorization": f"Bearer {ACCESS_TOKEN}", "Accept": "application/json"}
    return {"Authorization": f"Bearer {get_token()}", "Accept": "application/json"}


def teamwork_get(path: str) -> dict:
    """GET one Teamwork API resource using configured authentication."""
    resp = requests.get(
        f"{BASE_URL}{path}",
        headers=get_auth_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Teamwork API returned an unexpected response")
    return payload


def qwen_chat(messages: list[dict]) -> str:
    """Send a chat request to the configured OpenAI-compatible Qwen endpoint."""
    if not QWEN_API_KEY:
        raise RuntimeError("QWEN_API_KEY is required for task analysis")

    try:
        resp = requests.post(
            f"{QWEN_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {QWEN_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": QWEN_MODEL,
                "messages": messages,
                "temperature": 0,
                "max_tokens": QWEN_MAX_TOKENS,
                "response_format": {"type": "json_object"},
            },
            timeout=(QWEN_CONNECT_TIMEOUT, QWEN_READ_TIMEOUT),
        )
    except requests.exceptions.ConnectTimeout as exc:
        raise RuntimeError(
            f"Qwen connection timed out after {QWEN_CONNECT_TIMEOUT:g}s; "
            "check QWEN_API_BASE or provider availability"
        ) from exc
    except requests.exceptions.ReadTimeout as exc:
        raise RuntimeError(
            f"Qwen response timed out after {QWEN_READ_TIMEOUT:g}s; "
            "the model may be cold-starting or overloaded; retry the command"
        ) from exc
    if not resp.ok:
        detail = resp.text[:500]
        raise RuntimeError(f"Qwen API failed ({resp.status_code}): {detail}")

    try:
        return resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError("Qwen API returned an unexpected response") from exc


if __name__ == "__main__":
    print(json.dumps({"access_token": get_token()}, indent=2))
