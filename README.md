# auto-cr

`auto-cr` converts a Teamwork task into a GitHub SQL-request issue.

The automation reads the Teamwork task, identifies the requested COMREC operation, renders the matching local reference template, and creates an issue in the configured GitHub repository.

It does **not** execute SQL, connect to the database, run the generated shell commands, create a branch, commit files, or open a pull request.

## Quick Start

From this directory:

```bash
cd /Users/liamrhysslim/Codes/auto-cr
```

Create the virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Create `.env`:

```dotenv
GITHUB_TOKEN=ghp_your_token
GITHUB_OWNER=objectbrightph
GITHUB_REPO=sql-requests
GITHUB_LABEL=sql-request

TEAMWORK_EMAIL=your_teamwork_email
TEAMWORK_PASSWORD=your_teamwork_password
```

Run the automation:

```bash
./auto-cr "https://objectbright.teamwork.com/app/tasks/27255838"
```

`./auto-cr` always uses this project's `.venv`. This avoids accidentally running the system Python or a different pyenv environment.

Direct Python invocation is also supported:

```bash
.venv/bin/python agent_qwen.py \
  "https://objectbright.teamwork.com/app/tasks/27255838"
```

The script name `agent_qwen.py` is historical. SQL is currently rendered from the local reference files; it does not call Qwen.

## Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `GITHUB_TOKEN` | Yes | GitHub token with permission to create issues in the repository |
| `GITHUB_OWNER` | No | GitHub owner; defaults to `objectbrightph` |
| `GITHUB_REPO` | No | GitHub repository; defaults to `sql-requests` |
| `GITHUB_LABEL` | No | Issue label; defaults to `sql-request` |
| `TEAMWORK_EMAIL` | Yes for browser login | Teamwork account email |
| `TEAMWORK_PASSWORD` | Yes for browser login | Teamwork account password |

The Teamwork fetcher also accepts these aliases:

```dotenv
TW_EMAIL=your_teamwork_email
TW_PASSWORD=your_teamwork_password
```

or:

```dotenv
TW_USERNAME=your_teamwork_email
TW_PASSWORD=your_teamwork_password
```

Keep `.env` private. Do not commit tokens or passwords. Rotate any credential that has been exposed.

## Automation Workflow

```text
Teamwork task URL
        |
        v
Extract numeric task ID
        |
        v
Open Teamwork task with Playwright
        |
        v
Capture task API response and rendered task text
        |
        v
Extract title, feed ID, adapter ID, file ID, and rename filenames
        |
        v
Infer operation: reload, rename, or delete
        |
        +--> delete: ask for mode 1 or mode 2
        |
        v
Render reload.txt, rename.txt, delete1.txt, or delete2.txt
        |
        v
Render sql_request.txt as GitHub issue body
        |
        v
POST one issue to GitHub
```

### 1. Read the Teamwork URL

The URL must contain a numeric task ID:

```text
https://objectbright.teamwork.com/app/tasks/27255838
```

The numeric value `27255838` is passed to `fetch_task.py`.

### 2. Fetch the task

`fetch_task.py` opens the task page in a headless Chromium browser. If Teamwork redirects to login, it uses the credentials from `.env`.

The task API response is preferred. Rendered page text is used as a fallback.

The fetcher returns normalized JSON similar to:

```json
{
  "task_id": "27255838",
  "title": "Medical Mutual of OH Adapter ID 128 Feed ID 124 replace blob req by Zina 09222026",
  "description": "Hello, Please replace the blob for 2779396 with the file attached.",
  "feed_id": "124",
  "adapter_id": "128",
  "file_ids": ["2779396"],
  "rename_from": null,
  "rename_to": null,
  "operation": "reload"
}
```

To inspect task extraction without creating a GitHub issue:

```bash
.venv/bin/python fetch_task.py 27255838
```

### 3. Extract task fields

The task title or description must provide:

```text
Feed ID: 396
Adapter ID: 396
File ID: 2756788
```

The extractor also supports these file-ID formats:

```text
File ID: 2756788
FileID: 2756788
File #2756788
blob for 2756788
blob for #2756788
```

Rename tasks must provide both filenames:

```text
From: OLD_FILENAME
To: NEW_FILENAME
```

The process stops before GitHub issue creation when feed ID, adapter ID, file ID, title, or required rename destination is missing.

### 4. Infer the operation

Operation detection follows these rules:

- Title containing `delete`, `deletion`, or `remove` -> `delete`
- Title containing `rename`, `renamed`, or `change filename` -> `rename`
- `replace blob` with both `From:` and `To:` filenames -> `rename`
- Description containing a direct delete request -> `delete`
- Description containing rename wording or a valid `From:`/`To:` pair -> `rename`
- Otherwise -> `reload`

`replace blob` without a filename change is treated as `reload`. For example:

```text
Please replace the blob for 2779396 with the file attached.
```

### 5. Choose delete mode

Delete tasks require an interactive choice:

```text
Delete mode: choose 1 (delete1.txt) or 2 (delete2.txt):
```

Choose:

- `1` to render `delete1.txt`, which creates a new detail backup table.
- `2` to render `delete2.txt`, which inserts into the existing detail backup table.

No delete issue is created until a valid mode, `1` or `2`, is selected.

### 6. Render the SQL request

The selected reference file is loaded without changing its format:

| Operation | Template |
| --- | --- |
| Reload | `reload.txt` |
| Rename | `rename.txt` |
| Delete mode 1 | `delete1.txt` |
| Delete mode 2 | `delete2.txt` |

Only these placeholders are replaced:

```text
{feed_id}
{adapter_id}
{fileids}
{filename}
```

The reference template's comments, SQL statements, `commit;`, shell commands, and verification query are preserved.

### 7. Build the GitHub issue

The issue title is the exact Teamwork task title.

The body is rendered from `sql_request.txt`:

~~~text
# Project

- COMREC

# Teamwork

- {teamwork_link}

# Database (AIMSPRD, UNITED, etc.)

- AIMSPRD

# Schema (AGENCY, VUEUIG, etc.)

- AGENCY

# SQL

```sql
{the sql generated from python script}
```
~~~

The automation replaces `{teamwork_link}` with the original Teamwork URL and `{the sql generated from python script}` with the rendered reference request.

### 8. Create the issue

The script sends one request to:

```text
POST https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/issues
```

The payload contains:

```json
{
  "title": "Exact Teamwork task title",
  "body": "Rendered sql_request.txt body",
  "labels": ["sql-request"]
}
```

The resulting GitHub issue URL is printed to the terminal.

## Direct SQL Generators

These commands generate output locally without reading Teamwork or creating a GitHub issue:

```bash
.venv/bin/python reload.py \
  --feed-id 396 \
  --adapter-id 396 \
  --fileids 2756788
```

```bash
.venv/bin/python rename.py \
  --feed-id 396 \
  --adapter-id 396 \
  --fileids 2756788 \
  --filename NEW_NAME
```

```bash
.venv/bin/python delete.py \
  --feed-id 396 \
  --adapter-id 396 \
  --fileids 2756788 \
  --mode create
```

These commands print SQL and operational instructions. They do not execute them.

## Troubleshooting

### `ModuleNotFoundError: No module named ...`

Use the project interpreter:

```bash
source .venv/bin/activate
which python
```

Expected path:

```text
/Users/liamrhysslim/Codes/auto-cr/.venv/bin/python
```

Or bypass shell activation:

```bash
./auto-cr "https://objectbright.teamwork.com/app/tasks/27255838"
```

### Teamwork login error

Set credentials in `.env`:

```dotenv
TEAMWORK_EMAIL=your_teamwork_email
TEAMWORK_PASSWORD=your_teamwork_password
```

Then verify extraction:

```bash
.venv/bin/python fetch_task.py 27255838
```

### Missing required file ID

Inspect the task output:

```bash
.venv/bin/python fetch_task.py 27255838
```

Make sure the Teamwork task description contains a supported file-ID format such as `File ID: 2756788` or `blob for 2756788`.

### Delete task in a non-interactive shell

Delete mode requires input. Run the command from an interactive terminal and enter `1` or `2` when prompted.

### GitHub API error

Check:

- `GITHUB_TOKEN` is present and valid.
- The token can create issues in `GITHUB_OWNER/GITHUB_REPO`.
- The repository exists.
- The configured label exists if the repository requires existing labels.
