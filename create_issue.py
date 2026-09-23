#!/usr/bin/env python3
import urllib.request
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

url = "https://api.github.com/repos/objectbrightph/sql-requests/issues"
token = ""

body_text = """# Project

- COMREC

# Teamwork

- https://objectbright.teamwork.com/app/tasks/27255138

# Database

- AIMSPRD

# Schema

- AGENCY

# SQL

```sql
DELETE FROM ecs_header WHERE fileid IN (2756788);

DELETE FROM ecs_detail_type396 WHERE fileid IN (2756788);

UPDATE carrier_file_workflow SET filename='P_NCB_000QH00113_07312026', processdate = '', processstatus = '',is_export='' WHERE fileid IN (2756788);

commit;
```

---

**Operation**: Replace Blob (Rename)
- **Feed ID**: 396
- **Adapter ID**: 396
- **File ID**: 2756788
- **Rename**: From P_NCB_000QH00113_08032026 to P_NCB_000QH00113_07312026
"""

data = {
    "title": "Protective - Adapter ID 396 Feed ID 396 - Replace Blob - req by Jenna 09222026",
    "body": body_text,
    "labels": ["sql-request"]
}

req = urllib.request.Request(url, data=json.dumps(data).encode(), method="POST")
req.add_header("Authorization", f"token {token}")
req.add_header("Accept", "application/vnd.github+json")
req.add_header("Content-Type", "application/json")

try:
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode())
        print(f"Created issue #{result['number']}: {result['html_url']}")
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()}")
