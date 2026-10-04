"""Shared setup for the import scripts (run locally, not on Render)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from supabase import Client, create_client  # noqa: E402

BATCH_SIZE = 500


def get_client() -> Client:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()
    if not url or not key:
        sys.exit("❌ SUPABASE_URL and SUPABASE_KEY must be set (in .env or the environment).")
    return create_client(url, key)


def chunks(items: list, size: int = BATCH_SIZE):
    for i in range(0, len(items), size):
        yield items[i : i + size]
