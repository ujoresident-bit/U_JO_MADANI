"""Bulk import (or update) flashcards from a CSV file.

    python scripts/import_flashcards.py templates/flashcards_template.csv
    python scripts/import_flashcards.py my_cards.csv --dry-run

CSV columns: content (required), category, year, order_number (required),
is_active (optional: true/false).
order_number is the key: a row with an existing order_number UPDATES that
card; a new order_number ADDS a card. So the same CSV can be edited and
re-imported to fix text.
"""
from __future__ import annotations

import argparse
import csv
import sys

from _common import chunks, get_client

MAX_CONTENT = 3900
TRUE = {"true", "1", "yes", "y", "t"}
FALSE = {"false", "0", "no", "n", "f"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_file")
    parser.add_argument("--dry-run", action="store_true", help="validate only, write nothing")
    args = parser.parse_args()

    rows: dict[int, dict] = {}
    errors: list[str] = []

    with open(args.csv_file, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        missing = {"content", "order_number"} - set(headers)
        if missing:
            sys.exit(f"❌ Missing column(s): {', '.join(sorted(missing))}")
        reader.fieldnames = headers
        has_active = "is_active" in headers

        for line_no, rec in enumerate(reader, start=2):
            content = (rec.get("content") or "").strip()
            order_raw = (rec.get("order_number") or "").strip()
            if not content and not order_raw:
                continue  # blank line
            if not content:
                errors.append(f"row near line {line_no}: empty content")
                continue
            if len(content) > MAX_CONTENT:
                errors.append(f"order {order_raw}: content is {len(content)} chars (max {MAX_CONTENT})")
                continue
            try:
                order_number = int(order_raw)
                if order_number <= 0:
                    raise ValueError
            except ValueError:
                errors.append(f"row near line {line_no}: invalid order_number '{order_raw}'")
                continue
            if order_number in rows:
                errors.append(f"order {order_number}: duplicate order_number")
                continue

            year_raw = (rec.get("year") or "").strip()
            try:
                year = int(year_raw) if year_raw else None
            except ValueError:
                errors.append(f"order {order_number}: invalid year '{year_raw}'")
                continue

            row = {
                "content": content,
                "category": (rec.get("category") or "").strip() or None,
                "year": year,
                "order_number": order_number,
            }
            if has_active:
                val = (rec.get("is_active") or "true").strip().lower()
                if val not in TRUE | FALSE:
                    errors.append(f"order {order_number}: invalid is_active '{val}'")
                    continue
                row["is_active"] = val in TRUE
            rows[order_number] = row

    print(f"✔ Valid flashcards: {len(rows)}")
    if errors:
        print(f"⚠ Skipped {len(errors)} row(s):")
        for e in errors:
            print("   -", e)

    if args.dry_run or not rows:
        print("Dry run — nothing written." if args.dry_run else "Nothing to import.")
        return

    client = get_client()
    ordered = [rows[k] for k in sorted(rows)]
    for batch in chunks(ordered):
        client.table("flashcards").upsert(batch, on_conflict="order_number").execute()
    print(f"✅ Imported/updated {len(rows)} flashcards.")


if __name__ == "__main__":
    main()
