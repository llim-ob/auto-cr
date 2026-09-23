#!/usr/bin/env python3
"""Turn a Teamwork task into a GitHub issue.

The command reads a Teamwork task, infers the requested COMREC operation,
renders the matching reference request template, and creates an issue in the
configured GitHub repository. It never executes SQL or remote shell commands.

Usage:
    python agent_qwen.py <teamwork_link>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent


def load_local_env(path: Path) -> None:
    """Load simple KEY=value settings without requiring python-dotenv."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


BASE_DIR = Path(__file__).parent
load_local_env(BASE_DIR / ".env")
PLAYWRIGHT_SCRIPT = BASE_DIR / "fetch_task.py"
GITHUB_API = "https://api.github.com"
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "objectbrightph")
GITHUB_REPO = os.getenv("GITHUB_REPO", "sql-requests")
GITHUB_BASE_BRANCH = os.getenv("GITHUB_BASE_BRANCH", "main")


def parse_teamwork_link(link: str) -> dict[str, str]:
    """Extract the numeric Teamwork task ID from a task URL."""
    match = re.search(r"/tasks/(\d+)(?:[/?#]|$)", link)
    if not match:
        raise ValueError("Could not extract a task ID from the Teamwork URL")
    return {"task_id": match.group(1), "link": link}


def fetch_task_via_browser(task_id: str) -> dict:
    """Fetch task details using the existing Playwright adapter."""
    try:
        result = subprocess.run(
            [sys.executable, str(PLAYWRIGHT_SCRIPT), task_id],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Could not run Teamwork fetcher: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Teamwork fetch failed: {detail[:500]}")

    try:
        task = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Teamwork fetcher returned invalid JSON") from exc

    if task.get("error"):
        raise RuntimeError(task["error"])
    return task


def infer_operation(title: str, description: str) -> str:
    """Infer the supported operation from the task wording."""
    title_text = title.lower()
    if re.search(r"\b(delete|deletion|remove)\b", title_text):
        return "delete"
    has_rename_pair = bool(
        re.search(r"\bfrom\s*:\s*[\"']?[\w.-]+", description, re.IGNORECASE)
        and re.search(r"\bto\s*:\s*[\"']?[\w.-]+", description, re.IGNORECASE)
    )
    if re.search(r"\b(rename|renamed|change filename)\b", title_text):
        return "rename"
    if re.search(r"\breplace blob\b", title_text) and has_rename_pair:
        return "rename"
    if re.search(r"\b(reload|reprocess|retry|re-run|rerun)\b", title_text):
        return "reload"

    description_text = description.lower()
    if re.search(r"\b(rename|renamed|change filename)\b", description_text):
        return "rename"
    if re.search(r"\breplace blob\b", description_text) and has_rename_pair:
        return "rename"
    if re.search(r"\b(delete|deletion|remove)\s+(the|this|file|blob|record)", description_text):
        return "delete"
    if re.search(r"\b(reload|reprocess|retry|re-run|rerun)\b", description_text):
        return "reload"
    # Existing COMREC tasks that are not delete/rename requests are reloads.
    return "reload"


def validate_task(task: dict) -> dict:
    """Normalize task data and reject incomplete requests before SQL generation."""
    task = dict(task)
    task["operation"] = infer_operation(
        str(task.get("title", "")), str(task.get("description", ""))
    )
    task["feed_id"] = str(task.get("feed_id") or "")
    task["adapter_id"] = str(task.get("adapter_id") or "")
    task["file_ids"] = [str(value) for value in task.get("file_ids", []) if str(value)]
    task["title"] = str(task.get("title") or "").strip()

    missing = [
        name
        for name, value in (
            ("feed ID", task["feed_id"]),
            ("adapter ID", task["adapter_id"]),
            ("file ID", task["file_ids"]),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Task is missing required {', '.join(missing)}")
    if not task["title"]:
        raise ValueError("Task is missing its title")

    if task["operation"] == "rename":
        task["rename_to"] = str(task.get("rename_to") or "")
        if not task["rename_to"]:
            raise ValueError("Rename task is missing the destination filename (To: ...)")

    if task["operation"] == "delete":
        task["delete_mode"] = choose_delete_mode()

    return task


def choose_delete_mode() -> str:
    """Ask which delete reference template should be used."""
    while True:
        try:
            choice = input("Delete mode: choose 1 (delete1.txt) or 2 (delete2.txt): ").strip()
        except EOFError as exc:
            raise RuntimeError(
                "Delete operation requires a mode. Rerun interactively and choose 1 or 2."
            ) from exc
        if choice in {"1", "2"}:
            return choice
        print("Invalid choice. Enter 1 for delete1.txt or 2 for delete2.txt.")


def render_reference_template(task: dict) -> str:
    """Render the repository's reference text without changing its format."""
    operation = task["operation"]
    if operation == "delete":
        template_name = f"delete{task['delete_mode']}.txt"
    else:
        template_name = f"{operation}.txt"
    template = (BASE_DIR / template_name).read_text(encoding="utf-8")
    replacements = {
        "{feed_id}": task["feed_id"],
        "{adapter_id}": task["adapter_id"],
        "{fileids}": ",".join(task["file_ids"]),
        "{filename}": str(task.get("rename_to") or ""),
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template


def generate_request(task: dict) -> str:
    return render_reference_template(task)


def render_issue_body(task: dict, request_text: str) -> str:
    """Render the GitHub issue body from sql_request.txt."""
    template = (BASE_DIR / "sql_request.txt").read_text(encoding="utf-8")
    return template.replace("{teamwork_link}", task["link"]).replace(
        "{the sql generated from python script}", request_text
    )


def github_request(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    """Call GitHub's REST API and return its JSON response."""
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{GITHUB_API}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"GitHub API {method} {path} failed ({exc.code}): {detail}") from exc


def create_github_issue(task: dict, request_text: str, token: str) -> str:
    """Create one SQL request issue in the configured GitHub repository."""
    title = task["title"]
    body = render_issue_body(task, request_text)
    issue = github_request(
        "POST",
        f"/repos/{GITHUB_OWNER}/{GITHUB_REPO}/issues",
        token,
        {
            "title": title,
            "body": body,
            "labels": [os.getenv("GITHUB_LABEL", "sql-request")],
        },
    )
    return issue["html_url"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a GitHub issue from a Teamwork COMREC task")
    parser.add_argument("teamwork_link", help="Teamwork task URL")
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        print("ERROR: GITHUB_TOKEN is required", file=sys.stderr)
        return 2

    try:
        parsed_link = parse_teamwork_link(args.teamwork_link)
        task = {**parsed_link, **fetch_task_via_browser(parsed_link["task_id"])}
        task = validate_task(task)
        request_text = generate_request(task)
        print(f"Operation: {task['operation']}")
        print(f"Feed ID: {task['feed_id']}")
        print(f"Adapter ID: {task['adapter_id']}")
        print(f"File IDs: {', '.join(task['file_ids'])}")
        print("Creating GitHub issue...")
        print(f"Issue created: {create_github_issue(task, request_text, token)}")
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
