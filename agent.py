#!/usr/bin/env python3
"""
auto-cr agent - Analyze Teamwork task links and generate SQL scripts.

Usage:
    python agent.py <teamwork_link>

Example:
    python agent.py https://objectbright.teamwork.com/app/tasks/27255138

Requires:
    - GITHUB_TOKEN env var (for creating GitHub issues)
    - Teamwork browser session (logs in automatically)
"""

import sys
import re
import json
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent


def parse_teamwork_link(link: str) -> dict:
    """Extract task ID from teamwork link."""
    task_match = re.search(r'tasks/(\d+)', link)
    if not task_match:
        return {"error": "Could not extract task ID from URL"}
    return {"task_id": task_match.group(1), "link": link}


def fetch_task_via_browser(task_id: str) -> dict:
    """Fetch task details using Playwright browser automation."""
    import subprocess
    import json

    script = f'''
import sys
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        # Navigate to task
        page.goto("https://objectbright.teamwork.com/app/tasks/{task_id}")
        
        # Wait for login page or task page
        try:
            page.wait_for_selector('textbox[name="email"]', timeout=5000)
            # Login
            page.fill('textbox[name="email"]', "llim@objectbright.com")
            page.fill('input[type="password"]', "LL$2025!")
            page.check('checkbox[name="remember"]')
            page.click('button:has-text("Log in")')
            page.wait_for_load_state("networkidle", timeout=15000)
        except:
            pass  # Already logged in or different auth flow
        
        # Wait for task content
        page.wait_for_selector('[data-testid="task-title"] or h1 or .task-title', timeout=10000)
        
        # Extract task info
        title = page.text_content('h1, [data-testid="task-title"], .task-title') or ""
        description = page.text_content('.task-description, .description, [data-testid="task-description"]') or ""
        
        # Try to extract feed_id and adapter_id from title
        feed_id = None
        adapter_id = None
        feed_match = re.search(r'Feed\\s*ID[:\\s]*(\\d+)', title, re.IGNORECASE)
        if feed_match:
            feed_id = feed_match.group(1)
        adapter_match = re.search(r'Adapter\\s*ID[:\\s]*(\\d+)', title, re.IGNORECASE)
        if adapter_match:
            adapter_id = adapter_match.group(1)
        
        # Extract file IDs from description
        file_ids = []
        file_match = re.findall(r'File\\s*ID[:\\s]*(\\d+)', description, re.IGNORECASE)
        file_ids = file_match
        
        # Extract rename info
        rename_from = None
        rename_to = None
        from_match = re.search(r'From:\\s*["\']?([\\w_]+)', description, re.IGNORECASE)
        if from_match:
            rename_from = from_match.group(1)
        to_match = re.search(r'To:\\s*["\']?([\\w_]+)', description, re.IGNORECASE)
        if to_match:
            rename_to = to_match.group(1)
        
        # Determine operation type
        operation = "reload"
        if "delete" in title.lower():
            operation = "delete"
        elif "rename" in title.lower() or (rename_from and rename_to):
            operation = "rename"
        
        result = {
            "task_id": "{task_id}",
            "title": title,
            "description": description,
            "feed_id": feed_id,
            "adapter_id": adapter_id,
            "file_ids": file_ids,
            "rename_from": rename_from,
            "rename_to": rename_to,
            "operation": operation
        }
        
        print(json.dumps(result))
        browser.close()

if __name__ == "__main__":
    main()
'''

    try:
        result = subprocess.run(
            ["python3", "-c", script],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        else:
            print(f"Browser fetch error: {result.stderr[:500]}")
            return {"error": "Failed to fetch task via browser"}
    except Exception as e:
        return {"error": str(e)}


def generate_sql(operation: str, feed_id: str, adapter_id: str, file_ids: list, filename: str = None) -> str:
    """Generate SQL using the appropriate script."""
    if operation == "reload" or operation == "rename":
        cmd = ["python3", str(BASE_DIR / "reload.py")]
        cmd.extend(["--feed-id", feed_id, "--adapter-id", adapter_id, "--fileids", ",".join(file_ids)])
        if filename:
            cmd.extend(["--filename", filename])
    elif operation == "delete":
        cmd = ["python3", str(BASE_DIR / "delete.py")]
        cmd.extend(["--feed-id", feed_id, "--adapter-id", adapter_id, "--fileids", ",".join(file_ids), "--mode", "create"])
    else:
        return f"ERROR: Unknown operation '{operation}'"

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return result.stdout
        else:
            return f"ERROR: {result.stderr}"
    except Exception as e:
        return f"ERROR running script: {e}"


def create_github_issue(task_info: dict, sql_output: str) -> str:
    """Create GitHub issue in sql-requests repo."""
    import urllib.request

    token = task_info.get("github_token")
    if not token:
        return "ERROR: No GITHUB_TOKEN provided"

    # Extract SQL block from script output
    sql_block = ""
    in_sql = False
    for line in sql_output.split("\n"):
        if line.strip().startswith("--- SQL"):
            in_sql = True
            continue
        if in_sql and line.strip().startswith("```"):
            continue
        if in_sql and line.strip() == "```":
            break
        if in_sql and line.strip():
            sql_block += line + "\n"

    feed_id = task_info.get("feed_id", "N/A")
    adapter_id = task_info.get("adapter_id", "N/A")
    file_ids = task_info.get("file_ids", [])
    operation = task_info.get("operation", "unknown")
    rename_info = ""
    if task_info.get("rename_from") and task_info.get("rename_to"):
        rename_info = f"- **Rename**: From `{task_info['rename_from']}` to `{task_info['rename_to']}`\n"

    body = f"""# Project

- COMREC

# Teamwork

- {task_info.get('link', 'N/A')}

# Database

- AIMSPRD

# Schema

- AGENCY

# SQL

```sql
{sql_block.strip()}
```

---

**Operation**: {operation.capitalize()}
- **Feed ID**: {feed_id}
- **Adapter ID**: {adapter_id}
- **File IDs**: {', '.join(file_ids)}
{rename_info}"""

    url = "https://api.github.com/repos/objectbrightph/sql-requests/issues"
    data = {
        "title": f"COMREC - {operation.capitalize()} - Feed {feed_id} Adapter {adapter_id} - {', '.join(file_ids)}",
        "body": body,
        "labels": ["sql-request"]
    }

    req = urllib.request.Request(url, data=json.dumps(data).encode(), method="POST")
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return f"Issue created: {result['html_url']}"
    except urllib.error.HTTPError as e:
        return f"ERROR creating issue (HTTP {e.code}): {e.read().decode()[:200]}"
    except Exception as e:
        return f"ERROR creating issue: {e}"


def main():
    if len(sys.argv) < 2:
        print("Usage: python agent.py <teamwork_link>")
        print("Example: python agent.py https://objectbright.teamwork.com/app/tasks/27255138")
        print()
        print("Requires GITHUB_TOKEN env var for creating GitHub issues.")
        sys.exit(1)

    teamwork_link = sys.argv[1]
    github_token = sys.argv[2] if len(sys.argv) > 2 else None

    print("=" * 60)
    print("AUTO-CR AGENT")
    print("=" * 60)
    print(f"Teamwork Link: {teamwork_link}")
    print()

    # Parse link
    parsed = parse_teamwork_link(teamwork_link)
    if "error" in parsed:
        print(f"ERROR: {parsed['error']}")
        sys.exit(1)

    task_id = parsed["task_id"]
    print(f"Task ID: {task_id}")

    # Fetch task via browser
    print("\nFetching task details...")
    task_info = fetch_task_via_browser(task_id)

    if "error" in task_info:
        print(f"ERROR: {task_info['error']}")
        sys.exit(1)

    task_info["link"] = teamwork_link
    task_info["github_token"] = github_token

    print(f"Title: {task_info.get('title', 'N/A')}")
    print(f"Operation: {task_info.get('operation', 'N/A')}")
    print(f"Feed ID: {task_info.get('feed_id', 'N/A')}")
    print(f"Adapter ID: {task_info.get('adapter_id', 'N/A')}")
    print(f"File IDs: {task_info.get('file_ids', [])}")
    if task_info.get("rename_from"):
        print(f"Rename: {task_info['rename_from']} -> {task_info['rename_to']}")

    # Generate SQL
    print("\nGenerating SQL...")
    operation = task_info.get("operation", "reload")
    feed_id = task_info.get("feed_id", "396")
    adapter_id = task_info.get("adapter_id", "396")
    file_ids = task_info.get("file_ids", ["2756788"])
    filename = task_info.get("rename_to")

    sql_output = generate_sql(operation, feed_id, adapter_id, file_ids, filename)
    print(sql_output)

    # Create GitHub issue
    if github_token:
        print("\nCreating GitHub issue...")
        issue_url = create_github_issue(task_info, sql_output)
        print(issue_url)
    else:
        print("\nNo GITHUB_TOKEN provided. Skipping GitHub issue creation.")
        print("Set GITHUB_TOKEN env var or pass as second argument.")


if __name__ == "__main__":
    main()
