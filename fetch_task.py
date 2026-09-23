#!/usr/bin/env python3
"""Fetch and normalize a Teamwork task through the Teamwork web app."""

from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def load_local_env(path: Path) -> None:
    """Load simple KEY=value settings without requiring python-dotenv."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_local_env(Path(__file__).parent / ".env")

TEAMWORK_EMAIL = (
    os.getenv("TEAMWORK_EMAIL")
    or os.getenv("TW_EMAIL")
    or os.getenv("TW_USERNAME")
)
TEAMWORK_PASSWORD = os.getenv("TEAMWORK_PASSWORD") or os.getenv("TW_PASSWORD")


def text_value(value) -> str:
    """Convert API or HTML content into searchable plain text."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value)
    value = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(re.sub(r"\s+", " ", value)).strip()


def first_value(data: dict, *keys):
    for key in keys:
        value = data.get(key)
        if value not in (None, "", []):
            return value
    return None


def extract_task(task_id: str, task_data: dict, page_content: str, page_text: str) -> dict:
    """Extract fields from the task API payload, with rendered-page fallback."""
    data = task_data.get("task", task_data)
    if not isinstance(data, dict):
        data = {}

    title = text_value(first_value(data, "name", "title"))
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", page_content, re.DOTALL | re.IGNORECASE)
    if not title and title_match:
        title = text_value(title_match.group(1))

    description = text_value(first_value(data, "description", "content", "body"))
    if not description:
        description = text_value(page_text)

    source_text = f"{title}\n{description}"
    feed_id = first_value(data, "feedId", "feedID")
    adapter_id = first_value(data, "adapterId", "adapterID")
    feed_match = re.search(r"Feed\s*ID\s*[:#-]?\s*(\d+)", source_text, re.IGNORECASE)
    adapter_match = re.search(r"Adapter\s*ID\s*[:#-]?\s*(\d+)", source_text, re.IGNORECASE)
    if feed_match:
        feed_id = feed_match.group(1)
    if adapter_match:
        adapter_id = adapter_match.group(1)

    raw_file_ids = first_value(data, "fileIds", "fileIDs") or []
    if isinstance(raw_file_ids, (str, int)):
        raw_file_ids = [raw_file_ids]
    file_ids = [str(value) for value in raw_file_ids if value]
    file_ids.extend(
        re.findall(
            r"(?:File\s*ID|FileID|File\s*#)\s*[:#-]?\s*(\d+)",
            source_text,
            re.IGNORECASE,
        )
    )
    file_ids.extend(
        re.findall(r"\bblob\s+for\s+#?(\d+)\b", source_text, re.IGNORECASE)
    )
    file_ids = list(dict.fromkeys(file_ids))

    from_match = re.search(r"From\s*:\s*[\"']?([\w.-]+)", source_text, re.IGNORECASE)
    to_match = re.search(r"To\s*:\s*[\"']?([\w.-]+)", source_text, re.IGNORECASE)
    rename_from = from_match.group(1) if from_match else None
    rename_to = to_match.group(1) if to_match else None

    lowered_title = title.lower()
    operation = "reload"
    if re.search(r"\b(delete|deletion|remove)\b", lowered_title):
        operation = "delete"
    elif re.search(r"\b(rename|renamed|change filename)\b", lowered_title) or (
        rename_from and rename_to
    ):
        operation = "rename"

    return {
        "task_id": task_id,
        "title": title,
        "description": description,
        "feed_id": str(feed_id) if feed_id else None,
        "adapter_id": str(adapter_id) if adapter_id else None,
        "file_ids": file_ids,
        "rename_from": rename_from,
        "rename_to": rename_to,
        "operation": operation,
    }


def main() -> None:
    task_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not task_id:
        print(json.dumps({"error": "No task ID provided"}))
        raise SystemExit(1)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        task_payload = {}

        def capture_task_response(response):
            if f"/tasks/{task_id}.json" not in response.url or response.status != 200:
                return
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    task_payload.update(payload)
            except Exception:
                pass

        page.on("response", capture_task_response)
        page.goto(f"https://objectbright.teamwork.com/app/tasks/{task_id}", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)

        if "login" in page.url.lower() or "signin" in page.url.lower():
            if not TEAMWORK_EMAIL or not TEAMWORK_PASSWORD:
                raise RuntimeError(
                    "Teamwork login required. Add TEAMWORK_EMAIL and TEAMWORK_PASSWORD to .env "
                    "(or TW_EMAIL and TW_PASSWORD), then rerun the command"
                )
            page.locator("#loginemail").fill(TEAMWORK_EMAIL)
            page.locator("#loginpassword").fill(TEAMWORK_PASSWORD)
            remember = page.locator("#rememberMe")
            if remember.count() and not remember.is_checked():
                remember.check()
            page.locator('button[type="submit"]', has_text="Log in").click()
            page.wait_for_timeout(5000)

        if "login" in page.url.lower() or "signin" in page.url.lower():
            raise RuntimeError(
                "Teamwork login failed. Check TEAMWORK_EMAIL and TEAMWORK_PASSWORD in .env"
            )

        page.wait_for_timeout(3000)
        result = extract_task(task_id, task_payload, page.content(), page.inner_text("body"))
        browser.close()
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        raise SystemExit(1)
