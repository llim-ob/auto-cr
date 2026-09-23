#!/usr/bin/env python3
"""
delete.py - Delete file operation

Usage:
    python delete.py --feed-id <feed_id> --adapter-id <adapter_id> --fileids <id1,id2,...> --mode <create|insert>

Parameters:
    feed_id     - Feed ID from Teamwork task
    adapter_id  - Adapter ID from Teamwork task
    fileids     - Comma-separated list of file IDs
    mode        - 'create' (delete1.txt) or 'insert' (delete2.txt), default: create

Parameters from Teamwork task:
    - Feed ID
    - Adapter ID
    - File IDs (comma-separated)
"""

import argparse
import sys


def build_delete_create_sql(adapter_id: str, fileids: list[str]) -> str:
    """Build SQL for delete mode 1 (create new backup table)."""
    fileids_str = ",".join(fileids)
    sql_statements = [
        f"--create a new table for detail table backup and insert the data for backup",
        f"CREATE TABLE ecs_detail_type{adapter_id}_deleted AS (SELECT * FROM _detail_type WHERE fileid IN ({fileids_str}));",
        "",
        f"--insert the data in ecs_header_deleted for backup",
        f"INSERT INTO ecs_header_deleted (SELECT * FROM ecs_header WHERE fileid IN ({fileids_str}));",
        "",
        f"-- insert the data in carrier_file_workflow_deleted for backup",
        f"INSERT INTO carrier_file_workflow_deleted (SELECT * FROM carrier_file_workflow WHERE fileid IN ({fileids_str}));",
        "",
        f"DELETE FROM ecs_header WHERE fileid IN ({fileids_str});",
        "",
        f"DELETE FROM ecs_detail_type{adapter_id} WHERE fileid IN ({fileids_str});",
        "",
        f"DELETE FROM carrier_file_workflow WHERE fileid IN ({fileids_str});",
        "commit;",
    ]
    return "\n\n".join(sql_statements)


def build_delete_insert_sql(adapter_id: str, fileids: list[str]) -> str:
    """Build SQL for delete mode 2 (insert into existing backup table)."""
    fileids_str = ",".join(fileids)
    sql_statements = [
        f"--insert the data for backup to existing table",
        f"INSERT INTO ecs_detail_type{adapter_id}_deleted (SELECT * FROM _detail_type WHERE fileid IN ({fileids_str}));",
        "",
        f"--insert the data in ecs_header_deleted for backup",
        f"INSERT INTO ecs_header_deleted (SELECT * FROM ecs_header WHERE fileid IN ({fileids_str}));",
        "",
        f"-- insert the data in carrier_file_workflow_deleted for backup",
        f"INSERT INTO carrier_file_workflow_deleted (SELECT * FROM carrier_file_workflow WHERE fileid IN ({fileids_str}));",
        "",
        f"DELETE FROM ecs_header WHERE fileid IN ({fileids_str});",
        "",
        f"DELETE FROM _detail_type WHERE fileid IN ({fileids_str});",
        "",
        f"DELETE FROM carrier_file_workflow WHERE fileid IN ({fileids_str});",
        "commit;",
    ]
    return "\n\n".join(sql_statements)


def main():
    parser = argparse.ArgumentParser(description="Delete file operation")
    parser.add_argument("--feed-id", required=True, help="Feed ID from Teamwork task")
    parser.add_argument("--adapter-id", required=True, help="Adapter ID from Teamwork task")
    parser.add_argument("--fileids", required=True, help="Comma-separated file IDs")
    parser.add_argument(
        "--mode",
        choices=["create", "insert"],
        default="create",
        help="Delete mode: 'create' (delete1.txt) or 'insert' (delete2.txt)",
    )
    args = parser.parse_args()

    fileids = [f.strip() for f in args.fileids.split(",") if f.strip()]

    if not fileids:
        print("ERROR: No file IDs provided", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("DELETE OPERATION")
    print("=" * 60)
    print(f"Feed ID:    {args.feed_id}")
    print(f"Adapter ID: {args.adapter_id}")
    print(f"File IDs:   {', '.join(fileids)}")
    print(f"Mode:       {args.mode}")
    print("=" * 60)

    if args.mode == "create":
        print("\n--- SQL Statements (delete1.txt - create backup table) ---")
        print(build_delete_create_sql(args.adapter_id, fileids))
    else:
        print("\n--- SQL Statements (delete2.txt - insert into existing backup) ---")
        print(build_delete_insert_sql(args.adapter_id, fileids))


if __name__ == "__main__":
    main()
