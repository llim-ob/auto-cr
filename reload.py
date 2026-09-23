#!/usr/bin/env python3
"""
reload.py - Reload/Replace blob operation

Usage:
    python reload.py --feed-id <feed_id> --adapter-id <adapter_id> --fileids <id1,id2,...> [--filename <new_filename>]

Parameters:
    feed_id     - Feed ID from Teamwork task
    adapter_id  - Adapter ID from Teamwork task
    fileids     - Comma-separated list of file IDs
    filename    - Optional new filename (for rename-with-reload)
"""

import argparse
import sys


def build_reload_sql(feed_id: str, adapter_id: str, fileids: list[str], filename: str | None = None) -> str:
    """Build SQL statements for reload/rename operation."""
    fileids_str = ",".join(fileids)
    sql_statements = []

    # SQL: Delete from ecs_header
    sql_statements.append(f"DELETE FROM ecs_header WHERE fileid IN ({fileids_str});")

    # SQL: Delete from ecs_detail_type{adapter_id}
    sql_statements.append(f"DELETE FROM ecs_detail_type{adapter_id} WHERE fileid IN ({fileids_str});")

    # SQL: Update carrier_file_workflow
    if filename:
        sql_statements.append(
            f"UPDATE carrier_file_workflow SET filename='{filename}', processdate = '', processstatus = '',is_export='' WHERE fileid IN ({fileids_str});"
        )
    else:
        sql_statements.append(
            f"UPDATE carrier_file_workflow SET processdate = '', processstatus = '',is_export='' WHERE fileid IN ({fileids_str});"
        )

    sql_statements.append("commit;")

    return "\n\n".join(sql_statements)


def build_shell_commands() -> str:
    """Build shell commands for file cleanup and selector execution."""
    commands = [
        "login to 10.200.1.105",
        "cd /comrec_ecs/ctl_file",
        "rm *.bad",
        "cd /comrec_ecs/",
        "--Delete bad files",
        "cd /comrec_ecs/",
        "python selector.py :8aimsprd :9aimsbatch :10aimsbatch :12",
    ]
    return "\n".join(commands)


def build_verify_query(fileids: list[str]) -> str:
    """Build verification SQL query."""
    fileids_str = ",".join(fileids)
    return f"select * from ecs_header where fileid in ({fileids_str});"


def main():
    parser = argparse.ArgumentParser(description="Reload/Replace blob operation")
    parser.add_argument("--feed-id", required=True, help="Feed ID from Teamwork task")
    parser.add_argument("--adapter-id", required=True, help="Adapter ID from Teamwork task")
    parser.add_argument("--fileids", required=True, help="Comma-separated file IDs")
    parser.add_argument("--filename", default=None, help="Optional new filename for rename-with-reload")
    args = parser.parse_args()

    fileids = [f.strip() for f in args.fileids.split(",") if f.strip()]

    if not fileids:
        print("ERROR: No file IDs provided", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("RELOAD/RENAME OPERATION")
    print("=" * 60)
    print(f"Feed ID:    {args.feed_id}")
    print(f"Adapter ID: {args.adapter_id}")
    print(f"File IDs:   {', '.join(fileids)}")
    if args.filename:
        print(f"New Name:   {args.filename}")
    print("=" * 60)

    print("\n--- SQL Statements ---")
    print(build_reload_sql(args.feed_id, args.adapter_id, fileids, args.filename))

    print("\n--- Shell Commands ---")
    print(build_shell_commands())

    print("\n--- Verification Query ---")
    print(build_verify_query(fileids))

    print("\n-- Once reloaded and in GOOD status, check the query results and send the screenshot in TW")


if __name__ == "__main__":
    main()
