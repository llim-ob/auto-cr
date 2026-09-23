#!/usr/bin/env python3
"""
rename.py - Rename file operation (uses reload.py logic internally)

Usage:
    python rename.py --feed-id <feed_id> --adapter-id <adapter_id> --fileids <id1,id2,...> --filename <new_filename>

Parameters:
    feed_id     - Feed ID from Teamwork task
    adapter_id  - Adapter ID from Teamwork task
    fileids     - Comma-separated list of file IDs
    filename    - New filename (required)
"""

import argparse
import sys
from reload import build_reload_sql, build_shell_commands, build_verify_query


def main():
    parser = argparse.ArgumentParser(description="Rename file operation (uses reload logic)")
    parser.add_argument("--feed-id", required=True, help="Feed ID from Teamwork task")
    parser.add_argument("--adapter-id", required=True, help="Adapter ID from Teamwork task")
    parser.add_argument("--fileids", required=True, help="Comma-separated file IDs")
    parser.add_argument("--filename", required=True, help="New filename")
    args = parser.parse_args()

    fileids = [f.strip() for f in args.fileids.split(",") if f.strip()]

    if not fileids:
        print("ERROR: No file IDs provided", file=sys.stderr)
        sys.exit(1)

    if not args.filename:
        print("ERROR: --filename is required for rename operation", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("RENAME OPERATION")
    print("=" * 60)
    print(f"Feed ID:    {args.feed_id}")
    print(f"Adapter ID: {args.adapter_id}")
    print(f"File IDs:   {', '.join(fileids)}")
    print(f"New Name:   {args.filename}")
    print("=" * 60)

    print("\n--- SQL Statements (uses reload.py logic) ---")
    print(build_reload_sql(args.feed_id, args.adapter_id, fileids, args.filename))

    print("\n--- Shell Commands ---")
    print(build_shell_commands())

    print("\n--- Verification Query ---")
    print(build_verify_query(fileids))

    print("\n-- Once reloaded and in GOOD status, check the query results and send the screenshot in TW")


if __name__ == "__main__":
    main()
