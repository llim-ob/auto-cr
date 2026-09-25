# Repository Instructions

- Main workflow lives in `auto.py`: fetch Teamwork task -> extract IDs and filenames -> classify `reload`/`rename`/`delete` -> render `template/*.txt` -> create one GitHub issue.
- `tw_auth.py` loads `.env` at import time and handles Teamwork API/OAuth plus optional Qwen classification; do not hard-code credentials.
- Required runtime configuration is `GITHUB_TOKEN` and either `TW_API_KEY` or `TW_ACCESS_TOKEN`; `GITHUB_OWNER`, `GITHUB_REPO`, and `GITHUB_LABEL` have defaults in `auto.py`.
- Use the repository virtual environment: `.venv/bin/python -m pip install -r requirements.txt`.
- CLI path: `.venv/bin/python auto.py "<teamwork-task-url>"`; `./a` also accepts a URL, a macOS `.webloc` file, or prompts when double-clicked.
- A live CLI run fetches Teamwork and creates a GitHub issue. Do not run it with real credentials unless issue creation is intentional.
- Delete requests are interactive and require selecting template mode `1` or `2`; run from a terminal when testing that path.
- Templates are rendered text included in the GitHub issue. `auto.py` does not execute SQL, shell commands, database operations, or pull requests.
- Keep extraction changes in `extract_task()` aligned with the supported task formats documented in `README.md`; file IDs may come from API fields or task text.
- `create_issue.py` is a historical hard-coded example, not the production entrypoint; do not use it for normal changes.
- No test suite, build system, linter, or CI configuration is present. Minimum verification after Python edits: `python3 -m py_compile auto.py tw_auth.py`; use `.venv/bin/python` for import or focused behavior checks.
- Never commit `.env`, tokens, or generated virtual-environment/cache files.

# Documentation 
- every code changes that affect on how to use it update always the README.md on how to use it.
