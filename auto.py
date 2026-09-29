"""Turn a Teamwork task into a GitHub SQL-request issue."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from tw_auth import QWEN_API_KEY, qwen_chat, teamwork_get

BASE_DIR = Path(__file__).parent
TEMPLATE_DIR = BASE_DIR / "template"
GITHUB_API = "https://api.github.com"
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "objectbrightph")
GITHUB_REPO = os.getenv("GITHUB_REPO", "sql-requests")


def parse_teamwork_link(link: str) -> dict[str, str]:
    match = re.search(r"/tasks/(\d+)(?:[/?#]|$)", link)
    if not match:
        raise ValueError("Could not extract a task ID from the Teamwork URL")
    return {"task_id": match.group(1), "link": link}


def text_value(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value)
    value = html.unescape(re.sub(r"<[^>]+>", " ", value))
    # Teamwork's rich-text response can escape underscores in filenames as
    # `\_`; restore them before extracting filenames.
    value = value.replace(r"\_", "_")
    return re.sub(r"\s+", " ", value).strip()


def first_value(data: dict, *keys):
    for key in keys:
        value = data.get(key)
        if value not in (None, "", []):
            return value
    return None


def extract_rename_pair(source_text: str) -> tuple[str, str]:
    """Extract old and new filenames from labeled or natural-language text."""
    from_match = re.search(r"From\s*:\s*[\"']?([\w.-]+)", source_text, re.IGNORECASE)
    to_match = re.search(r"To\s*:\s*[\"']?([\w.-]+)", source_text, re.IGNORECASE)
    if from_match and to_match:
        return from_match.group(1), to_match.group(1)

    # Also support wording such as: "from OLD_NAME to NEW_NAME" and
    # "from (OLD_NAME) to (NEW_NAME)".
    natural_match = re.search(
        r"\bfrom\s+\(?[\"']?([\w.-]+)[\"']?\)?\s+to\s+\(?[\"']?([\w.-]+)[\"']?\)?",
        source_text,
        re.IGNORECASE,
    )
    if natural_match:
        return natural_match.group(1), natural_match.group(2)

    # A task may identify only the destination, for example:
    # "Update filename to NEW_NAME" or "New filename: NEW_NAME".
    destination_patterns = (
        r"\bupdate[ \t]+file[ \t]*name(?:[ \t]+(?:to|as|with|is))?[ \t]*[:=-]?[ \t]*[\"']?([\w.-]+)",
        r"\b(?:new|destination)[ \t]+file[ \t]*name[ \t]*(?:is[ \t]*)?[:=-][ \t]*[\"']?([\w.-]+)",
    )
    for pattern in destination_patterns:
        destination_match = re.search(pattern, source_text, re.IGNORECASE)
        if destination_match and destination_match.group(1).lower() not in {
            "from",
            "to",
            "the",
        }:
            return "", destination_match.group(1)
    return "", ""


def extract_task(task_id: str, payload: dict) -> dict:
    data = payload.get("task", payload)
    if not isinstance(data, dict):
        raise RuntimeError("Teamwork task response did not contain a task")

    title = text_value(first_value(data, "name", "title"))
    description = text_value(first_value(data, "description", "content", "body"))
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
        re.findall(r"(?:File\s*ID|FileID|File\s*#)\s*[:#-]?\s*(\d+)", source_text, re.IGNORECASE)
    )
    file_ids.extend(
        re.findall(r"\bFile\s+(\d+)\b", source_text, re.IGNORECASE)
    )
    file_ids.extend(
        re.findall(
            r"\b(\d+)\s*-\s*\d{1,2}/\d{1,2}/\d{4}\b",
            source_text,
        )
    )
    file_ids.extend(
        re.findall(r"\bblob(?:\s+for)?\s*[:#-]?\s*(\d+)\b", source_text, re.IGNORECASE)
    )
    file_ids.extend(
        re.findall(r"\bfor\s+(\d+)\b", source_text, re.IGNORECASE)
    )

    rename_from, rename_to = extract_rename_pair(source_text)

    return {
        "task_id": task_id,
        "title": title,
        "description": description,
        "feed_id": str(feed_id) if feed_id else "",
        "adapter_id": str(adapter_id) if adapter_id else "",
        "file_ids": list(dict.fromkeys(file_ids)),
        "rename_from": rename_from,
        "rename_to": rename_to,
    }


def fetch_task(task_id: str) -> dict:
    """Fetch task data directly through the Teamwork API, without browser login."""
    return extract_task(
        task_id,
        teamwork_get(f"/projects/api/v3/tasks/{task_id}.json"),
    )


def analyze_task_hardcoded(task: dict) -> dict:
    """Classify supported operations without an external model."""
    title_text = task["title"].lower()
    description = task["description"]
    description_text = description.lower()
    has_rename_pair = bool(task["rename_from"] and task["rename_to"])
    title_pair = extract_rename_pair(task["title"])
    description_pair = extract_rename_pair(description)
    title_has_rename_pair = bool(title_pair[0] and title_pair[1])
    description_has_rename_pair = bool(description_pair[0] and description_pair[1])
    rename_trigger = (
        r"\b(rename|renamed|change\s+filename|update\s+file\s+name|"
        r"update\s+filename)\b"
    )

    if re.search(r"\b(delete|deletion|remove)\b", title_text):
        operation = "delete"
    elif re.search(rename_trigger, title_text) or title_has_rename_pair:
        operation = "rename"
    elif re.search(r"\breplace blob\b", title_text) and has_rename_pair:
        operation = "rename"
    elif re.search(r"\b(reload|reprocess|retry|re-run|rerun)\b", title_text):
        operation = "reload"
    elif re.search(rename_trigger, description_text) or description_has_rename_pair:
        operation = "rename"
    elif re.search(r"\breplace blob\b", description_text) and has_rename_pair:
        operation = "rename"
    elif re.search(r"\b(delete|deletion|remove)\s+(the|this|file|blob|record)", description_text):
        operation = "delete"
    elif re.search(r"\b(reload|reprocess|retry|re-run|rerun)\b", description_text):
        operation = "reload"
    else:
        operation = "reload"

    return {
        "operation": operation,
        "rename_to": task["rename_to"] if operation == "rename" else "",
        "request_details": "For Reload" if operation == "reload" else "",
        "rationale": "Matched local COMREC operation rules.",
        "analyzer": "hardcoded",
    }


def analyze_task(task: dict, operation: str | None = None) -> dict:
    """Select an explicit operation or analyze the Teamwork task."""
    if operation:
        return {
            "operation": "reload" if operation == "replace-blob" else operation,
            "rename_to": task["rename_to"] if operation == "rename" else "",
            "request_details": (
                "For Reload / BLOB Update"
                if operation == "replace-blob"
                else "For Reload" if operation == "reload" else ""
            ),
            "rationale": (
                "Explicit operation flag selected "
                f"{operation.replace('-', ' ')}."
            ),
            "analyzer": "explicit flag",
        }

    # Strong local filename triggers must remain deterministic even when Qwen
    # is configured. Qwen is still used for wording not covered by these rules.
    local_analysis = analyze_task_hardcoded(task)
    if local_analysis["operation"] == "rename":
        return local_analysis
    if not QWEN_API_KEY:
        return local_analysis

    prompt = {
        "title": task["title"],
        "description": task["description"],
        "rename_from": task["rename_from"],
        "rename_to": task["rename_to"],
        "feed_id": task["feed_id"],
        "adapter_id": task["adapter_id"],
        "file_ids": task["file_ids"],
    }
    content = qwen_chat(
        [
            {
                "role": "system",
                "content": (
                    "Classify a COMREC Teamwork task. Return JSON only with keys "
                    "operation, rename_to, rationale. operation must be exactly "
                    "reload, rename, or delete. Use rename only for a filename change. "
                    "Treat 'update file name', 'update filename', and 'from OLD to NEW' "
                    "as filename-change wording. "
                    "Use delete only when the task asks to remove/delete data. "
                    "Use reload for replacing/reprocessing a blob without deletion or "
                    "filename change. rename_to must be an empty string unless operation "
                    "is rename. Do not invent IDs or filenames."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=True)},
        ]
    )
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if not fenced:
            raise RuntimeError("Qwen returned invalid task-analysis JSON") from exc
        result = json.loads(fenced.group(1))

    operation = result.get("operation")
    if operation not in {"reload", "rename", "delete"}:
        raise RuntimeError("Qwen returned an unsupported operation")
    # Prefer the filename parsed directly from the Teamwork task. This prevents
    # a model response from accidentally using the task title as the filename.
    rename_to = str(task["rename_to"] or result.get("rename_to") or "").strip()
    if operation == "rename" and not rename_to:
        raise RuntimeError("Qwen classified task as rename but returned no destination filename")
    if operation != "rename":
        rename_to = ""
    return {
        "operation": operation,
        "rename_to": rename_to,
        "request_details": "For Reload" if operation == "reload" else "",
        "rationale": str(result.get("rationale") or ""),
        "analyzer": "qwen",
    }


def append_database_file_extension(task: dict) -> dict:
    """Append the production filename extension using a read-only Oracle query."""
    if task["operation"] != "rename":
        return task

    try:
        import oracledb
    except ImportError as exc:
        raise RuntimeError(
            "The oracledb package is required for rename tasks; install requirements.txt"
        ) from exc

    db_connection = os.getenv("DB_CONNECTION", "oracle").strip().lower()
    if db_connection != "oracle":
        raise RuntimeError("DB_CONNECTION must be oracle for rename filename lookup")

    required = {
        "DB_DATABASE": os.getenv("DB_DATABASE", "").strip(),
        "DB_HOST": os.getenv("DB_HOST", "").strip(),
        "DB_PASSWORD": os.getenv("DB_PASSWORD", ""),
        "DB_PORT": os.getenv("DB_PORT", "").strip(),
        "DB_USERNAME": os.getenv("DB_USERNAME", "").strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            "Rename filename lookup requires database settings: " + ", ".join(missing)
        )

    try:
        port = int(required["DB_PORT"])
    except ValueError as exc:
        raise RuntimeError("DB_PORT must be an integer") from exc

    # AIMSPRD uses an Oracle server version that is not supported by the
    # python-oracledb Thin mode. Thick mode requires Oracle Instant Client.
    client_lib = os.getenv("DB_ORACLE_CLIENT_LIB", "").strip()
    try:
        if oracledb.is_thin_mode():
            if client_lib:
                oracledb.init_oracle_client(lib_dir=client_lib)
            else:
                oracledb.init_oracle_client()
    except oracledb.Error as exc:
        raise RuntimeError(
            "AIMSPRD requires python-oracledb Thick mode, but Oracle Instant Client "
            "could not be loaded. Install Oracle Instant Client and set "
            "DB_ORACLE_CLIENT_LIB to its directory in .env."
        ) from exc

    connection = None
    extensions = set()
    try:
        dsn = oracledb.makedsn(
            required["DB_HOST"],
            port,
            service_name=required["DB_DATABASE"],
        )
        connection = oracledb.connect(
            user=required["DB_USERNAME"],
            password=required["DB_PASSWORD"],
            dsn=dsn,
        )
        with connection.cursor() as cursor:
            for file_id in task["file_ids"]:
                try:
                    numeric_file_id = int(file_id)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"Invalid file ID for filename lookup: {file_id}"
                    ) from exc

                # Read-only by design: this is the only statement executed here.
                cursor.execute(
                    "SELECT filename FROM carrier_file_workflow WHERE fileid = :fileid",
                    fileid=numeric_file_id,
                )
                row = cursor.fetchone()
                if not row or not row[0]:
                    raise RuntimeError(
                        f"No filename found in carrier_file_workflow for file ID {file_id}"
                    )
                extension = Path(str(row[0]).strip()).suffix.lstrip(".")
                if not extension:
                    raise RuntimeError(
                        f"Filename for file ID {file_id} has no file extension"
                    )
                extensions.add(extension.lower())
    except oracledb.Error as exc:
        raise RuntimeError(f"Read-only Oracle filename lookup failed: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()

    if len(extensions) != 1:
        raise RuntimeError(
            "Rename file IDs must resolve to exactly one file type; "
            f"found: {', '.join(sorted(extensions)) or 'none'}"
        )

    extension = next(iter(extensions))
    filename = task["rename_to"].strip()
    current_suffix = Path(filename).suffix
    expected_suffix = f".{extension}"
    if current_suffix.lower() != expected_suffix:
        filename = (
            f"{filename}{expected_suffix}"
            if not current_suffix
            else f"{filename[:-len(current_suffix)]}{expected_suffix}"
        )
    task["rename_to"] = filename
    return task


def validate_task(task: dict, analysis: dict) -> dict:
    task = dict(task)
    task.update(analysis)
    missing = [
        name
        for name, value in (
            ("feed ID", task["feed_id"]),
            ("adapter ID", task["adapter_id"]),
            ("file ID", task["file_ids"]),
            ("title", task["title"]),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Task is missing required {', '.join(missing)}")
    if task["operation"] == "rename" and not task["rename_to"]:
        raise ValueError("Rename task is missing the destination filename (To: ...)")
    return task


def choose_delete_mode() -> str:
    while True:
        choice = input("Delete mode: choose 1 (delete1.txt) or 2 (delete2.txt): ").strip()
        if choice in {"1", "2"}:
            return choice
        print("Invalid choice. Enter 1 for delete1.txt or 2 for delete2.txt.")


def render_reference_template(task: dict) -> str:
    template_name = (
        f"delete{choose_delete_mode()}.txt" if task["operation"] == "delete" else f"{task['operation']}.txt"
    )
    template = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
    replacements = {
        "{feed_id}": task["feed_id"],
        "{adapter_id}": task["adapter_id"],
        "{fileids}": ",".join(task["file_ids"]),
        "{filename}": task["rename_to"],
        "{request_details}": task.get("request_details", "For Reload"),
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template


def render_issue_body(task: dict, request_text: str) -> str:
    template = (BASE_DIR / "sql_request.txt").read_text(encoding="utf-8")
    return template.replace("{teamwork_link}", task["link"]).replace(
        "{the sql generated from python script}", request_text
    )


def github_request(method: str, path: str, token: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{GITHUB_API}{path}",
        data=json.dumps(payload).encode(),
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
        raise RuntimeError(f"GitHub API failed ({exc.code}): {detail}") from exc


def create_github_issue(task: dict, request_text: str) -> str:
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")
    issue = github_request(
        "POST",
        f"/repos/{GITHUB_OWNER}/{GITHUB_REPO}/issues",
        token,
        {
            "title": task["title"],
            "body": render_issue_body(task, request_text),
            "labels": [os.getenv("GITHUB_LABEL", "sql-request")],
        },
    )
    return issue["html_url"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a GitHub issue from a Teamwork COMREC task")
    parser.add_argument("teamwork_link", help="Teamwork task URL")
    operation_group = parser.add_mutually_exclusive_group()
    operation_group.add_argument(
        "--operation",
        choices=("reload", "delete", "rename", "replace-blob"),
        help="Use this operation instead of analyzing the Teamwork task",
    )
    operation_group.add_argument(
        "--reload",
        dest="operation",
        action="store_const",
        const="reload",
        help="Force reload operation",
    )
    operation_group.add_argument(
        "--delete",
        dest="operation",
        action="store_const",
        const="delete",
        help="Force delete operation",
    )
    operation_group.add_argument(
        "--rename",
        dest="operation",
        action="store_const",
        const="rename",
        help="Force rename operation",
    )
    operation_group.add_argument(
        "--replace-blob",
        dest="operation",
        action="store_const",
        const="replace-blob",
        help="Force replace-blob operation using the reload template",
    )
    args = parser.parse_args()

    try:
        task = {**parse_teamwork_link(args.teamwork_link)}
        task.update(fetch_task(task["task_id"]))
        analysis = analyze_task(task, args.operation)
        task = validate_task(task, analysis)
        task = append_database_file_extension(task)
        request_text = render_reference_template(task)
        print(f"Operation: {task['operation']}")
        print(f"Analyzer: {task['analyzer']}")
        print(f"Analysis rationale: {task['rationale']}")
        print(f"Feed ID: {task['feed_id']}")
        print(f"Adapter ID: {task['adapter_id']}")
        print(f"File IDs: {', '.join(task['file_ids'])}")
        if task["operation"] == "rename":
            print(f"Rename destination: {task['rename_to']}")
        print(f"")
        print(f"CHECK ALWAYS THE QUERY IN THE ISSUE BEFORE SUBMITTING IT")
        print(f"Issue created: {create_github_issue(task, request_text)}")
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
