"""Bulk import allowed users from a CSV file.

    python scripts/import_users.py templates/allowed_users_template.csv
    python scripts/import_users.py my_users.csv --dry-run

CSV columns: username (required), status (optional: active | disabled).
"@User1" and "user1" are treated as the same user. Re-running is safe:
existing usernames are updated (status), new ones are added, and linked
Telegram IDs / progress are never touched.
"""
from __future__ import annotations

import argparse
import csv
import sys

from _common import chunks, get_client
from utils import is_valid_username, normalize_username

VALID_STATUS = {"active", "disabled"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_file")
    parser.add_argument("--dry-run", action="store_true", help="validate only, write nothing")
    args = parser.parse_args()

    rows: dict[str, dict] = {}
    errors: list[str] = []

    with open(args.csv_file, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        if "username" not in headers:
            sys.exit("❌ The CSV must have a 'username' column.")
        reader.fieldnames = headers

        for line_no, record in enumerate(reader, start=2):
            raw = (record.get("username") or "").strip()
            if not raw:
                continue
            username = normalize_username(raw)
            status = (record.get("status") or "active").strip().lower() or "active"
            if not is_valid_username(username):
                errors.append(f"line {line_no}: invalid username '{raw}'")
                continue
            if status not in VALID_STATUS:
                errors.append(f"line {line_no}: invalid status '{status}' (use active/disabled)")
                continue
            rows[username] = {"username": username, "status": status}  # last one wins

    print(f"✔ Valid users: {len(rows)}")
    if errors:
        print(f"⚠ Skipped {len(errors)} row(s):")
        for e in errors:
            print("   -", e)

    if args.dry_run or not rows:
        print("Dry run — nothing written." if args.dry_run else "Nothing to import.")
        return

    client = get_client()
    for batch in chunks(list(rows.values())):
        client.table("allowed_users").upsert(batch, on_conflict="username").execute()
    print(f"✅ Imported/updated {len(rows)} users.")


if __name__ == "__main__":
    main()
