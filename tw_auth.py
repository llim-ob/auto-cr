#!/usr/bin/env python3
"""Authenticate with Teamwork.com API using OAuth2 client credentials."""

import requests
import json
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

CLIENT_ID = os.getenv("TW_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("TW_CLIENT_SECRET", "")
BASE_URL = "https://objectbright.teamwork.com"

# Qwen API config
QWEN_API_BASE = "https://gpu.ltcglobal.com/v1"
QWEN_API_KEY = "sk-fl-ganmgJJ0IhYu6q4akXw"
QWEN_MODEL = "qwen-mtp-35b"

def get_token():
    resp = requests.post(
        f"{BASE_URL}/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

if __name__ == "__main__":
    token = get_token()
    print(json.dumps({"access_token": token}, indent=2))
