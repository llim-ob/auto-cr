# auto-cr

`auto-cr` converts a Teamwork task link into a GitHub issue containing the SQL and operational instructions for a COMREC request.

It reads the Teamwork task, determines whether the request is a reload, rename, or delete operation, fills the matching local template, and creates one issue in the configured GitHub repository.

The script does not execute SQL, connect to a database, run shell commands, or create a pull request.

## How To Use It

### 1. Install dependencies

From the project directory:

```bash
cd /Users/liamrhysslim/Codes/auto-cr
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

If `.venv` already exists, only the install command is needed.

### 2. Configure credentials

Create `.env` in the project directory:

```dotenv
# GitHub issue destination
GITHUB_TOKEN=your_github_token
GITHUB_OWNER=objectbrightph
GITHUB_REPO=sql-requests
GITHUB_LABEL=sql-request

# Teamwork authentication: use either API key or OAuth access token
TW_API_KEY=your_teamwork_api_key
# TW_ACCESS_TOKEN=your_teamwork_access_token

# Optional Qwen task classification
# QWEN_API_KEY=your_qwen_api_key
# QWEN_API_BASE=https://gpu.ltcglobal.com/v1
# QWEN_MODEL=qwen-mtp-35b
```

Required values:

| Variable | Required | Purpose |
| --- | --- | --- |
| `GITHUB_TOKEN` | Yes | Allows the script to create GitHub issues. |
| `TW_API_KEY` or `TW_ACCESS_TOKEN` | Yes | Allows the script to read the Teamwork task. |
| `GITHUB_OWNER` | No | GitHub owner. Defaults to `objectbrightph`. |
| `GITHUB_REPO` | No | GitHub repository. Defaults to `sql-requests`. |
| `GITHUB_LABEL` | No | Issue label. Defaults to `sql-request`. |
| `QWEN_API_KEY` | No | Enables Qwen classification. Without it, local rules are used. |

Keep `.env` private. Never commit API keys or tokens.

### 3. Prepare the Teamwork task

The Teamwork task title or description should include:

- Feed ID, for example `Feed ID: 396`
- Adapter ID, for example `Adapter ID: 396`
- File ID, for example `File ID: 2756788` or `blob for 2756788`

For a rename request, include both filenames:

```text
From: OLD_FILENAME
To: NEW_FILENAME
```

The script also reads `feedId`, `adapterId`, and `fileIds` when those values are present in the Teamwork API response.

### 4. Paste the Teamwork link into the command

Run `auto.py` with the Teamwork task URL:

```bash
.venv/bin/python auto.py \
  "https://objectbright.teamwork.com/app/tasks/27255838"
```

The URL must contain a numeric task ID in the `/tasks/<id>` path.

For a delete request, the command pauses and asks which delete template to use:

```text
Delete mode: choose 1 (delete1.txt) or 2 (delete2.txt):
```

Enter `1` or `2`, then let the command finish.

### 5. Open the created GitHub issue

When successful, the command prints the created issue URL:

```text
Issue created: https://github.com/objectbrightph/sql-requests/issues/123
```

## Teamwork Link To GitHub Issue Flow

```text
Paste Teamwork task link into auto.py
                 |
                 v
Extract numeric Teamwork task ID
                 |
                 v
Authenticate with Teamwork API
                 |
                 v
Fetch task title and description
                 |
                 v
Extract feed ID, adapter ID, file IDs, and rename filenames
                 |
                 v
Classify operation: reload, rename, or delete
                 |
                 +--> delete: ask for template mode 1 or 2
                 |
                 v
Load and fill operation template from template/
                 |
                 v
Insert rendered request into sql_request.txt
                 |
                 v
Create GitHub issue with Teamwork title, link, SQL, and label
                 |
                 v
Print GitHub issue URL
```

### 1. Parse the Teamwork link

`auto.py` extracts the numeric task ID from the link. It rejects links that do not contain a task ID.

### 2. Fetch the task

`tw_auth.py` authenticates with Teamwork and fetches:

```text
GET https://objectbright.teamwork.com/projects/api/v3/tasks/<task_id>.json
```

The script supports Teamwork API-key authentication with `TW_API_KEY` and OAuth bearer authentication with `TW_ACCESS_TOKEN`.

### 3. Extract task data

The title and description are normalized, then the script extracts:

| Value | Supported examples |
| --- | --- |
| Feed ID | `Feed ID: 396` |
| Adapter ID | `Adapter ID: 396` |
| File ID | `File ID: 2756788`, `FileID 2756788`, `File #2756788`, `blob for 2756788` |
| Rename source | `From: OLD_FILENAME` |
| Rename destination | `To: NEW_FILENAME` |

The script stops before creating the issue if feed ID, adapter ID, file ID, or title is missing. Rename operations also require a destination filename.

### 4. Classify the operation

If `QWEN_API_KEY` is configured, Qwen classifies the task. Qwen must return one of:

- `reload` for replacing or reprocessing a blob
- `rename` for changing a filename
- `delete` for removing data

Without Qwen, local deterministic rules classify the title and description. Unmatched requests default to `reload`.

Qwen does not generate SQL. It only selects the operation and, for a rename, returns the destination filename.

### 5. Render the request template

Operation templates are stored in `template/`:

| Operation | Template |
| --- | --- |
| Reload | `template/reload.txt` |
| Rename | `template/rename.txt` |
| Delete mode 1 | `template/delete1.txt` |
| Delete mode 2 | `template/delete2.txt` |

The selected template is filled with:

| Placeholder | Value |
| --- | --- |
| `{feed_id}` | Extracted Teamwork feed ID |
| `{adapter_id}` | Extracted Teamwork adapter ID |
| `{fileids}` | File IDs joined with commas |
| `{filename}` | Rename destination filename |

The templates contain the SQL and any required shell commands or verification queries. Those instructions are included as text in the GitHub issue; they are not executed by `auto.py`.

### 6. Build the GitHub issue body

`sql_request.txt` is the outer GitHub issue template. It remains in the project root and contains the project, Teamwork, database, schema, and SQL sections.

The script replaces:

- `{teamwork_link}` with the original Teamwork URL
- `{the sql generated from python script}` with the selected, filled operation template

The GitHub issue title is the exact Teamwork task title.

### 7. Create the issue

The script sends one request to:

```text
POST https://api.github.com/repos/<GITHUB_OWNER>/<GITHUB_REPO>/issues
```

The request includes:

```json
{
  "title": "Teamwork task title",
  "body": "Rendered sql_request.txt content",
  "labels": ["sql-request"]
}
```

The label comes from `GITHUB_LABEL`.

## OAuth Setup

API-key authentication is simplest. If OAuth is required:

1. Configure the Teamwork app client ID, client secret, and registered redirect URI.
2. Complete the Teamwork authorization flow and obtain the one-time authorization code.
3. Set `TW_CLIENT_ID`, `TW_CLIENT_SECRET`, `TW_AUTH_CODE`, and `TW_REDIRECT_URI` in `.env`.
4. Run `tw_auth.py` once to exchange the code for an access token.
5. Store the returned token as `TW_ACCESS_TOKEN` and remove `TW_AUTH_CODE`.

## Troubleshooting

### Teamwork authentication error

Confirm that `.env` contains either:

```dotenv
TW_API_KEY=your_teamwork_api_key
```

or:

```dotenv
TW_ACCESS_TOKEN=your_teamwork_access_token
```

### Missing task data

Add feed, adapter, and file IDs to the Teamwork title or description. Rename requests also need a `To:` filename.

### Delete prompt does not work

Delete mode is interactive. Run the command from a terminal and enter `1` or `2` when prompted.

### GitHub API error

Check that:

- `GITHUB_TOKEN` is valid and can create issues.
- `GITHUB_OWNER` and `GITHUB_REPO` identify the correct repository.
- The configured `GITHUB_LABEL` is available in that repository.

### Python dependency error

Use the project virtual environment directly:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python auto.py "<teamwork-task-link>"
```
