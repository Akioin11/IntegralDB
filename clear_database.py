"""Utility script to wipe Supabase tables.

Usage:
    python clear_database.py              # clears the default tables (documents)
    python clear_database.py --tables documents suppliers products
    python clear_database.py --yes        # skip interactive confirmation

The script requires SUPABASE_URL and SUPABASE_KEY in your environment or .env.
"""
import argparse
import os
import sys
from typing import List

from dotenv import load_dotenv
from supabase import Client, create_client


def _get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        return ""
    return val.strip().strip('"').strip("'")


def _confirm(force: bool, tables: List[str]) -> bool:
    if force:
        return True
    joined = ", ".join(tables)
    prompt = f"This will permanently delete all rows from: {joined}. Continue? [y/N]: "
    answer = input(prompt).strip().lower()
    return answer in {"y", "yes"}


def _clear_tables(supabase: Client, tables: List[str]):
    for table in tables:
        try:
            # The neq filter satisfies the API requirement for a condition while targeting every row.
            resp = supabase.table(table).delete().neq("id", None).execute()
            deleted_count = None
            if hasattr(resp, "count") and resp.count is not None:
                deleted_count = resp.count
            elif hasattr(resp, "data") and resp.data is not None:
                deleted_count = len(resp.data)
            msg = f"Cleared table '{table}'"
            if deleted_count is not None:
                msg += f" (deleted {deleted_count} rows)"
            print(msg)
        except Exception as exc:  # pragma: no cover - best-effort logging
            print(f"Failed to clear table '{table}': {exc}")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Delete all rows from Supabase tables.")
    parser.add_argument(
        "--tables",
        nargs="+",
        default=["documents"],
        help="Tables to clear. Default: documents",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt.",
    )
    args = parser.parse_args()

    load_dotenv()
    supabase_url = _get_env("SUPABASE_URL")
    supabase_key = _get_env("SUPABASE_KEY")

    missing = [name for name, val in {"SUPABASE_URL": supabase_url, "SUPABASE_KEY": supabase_key}.items() if not val]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    if not _confirm(args.yes, args.tables):
        print("Aborted. No changes were made.")
        return

    supabase: Client = create_client(supabase_url, supabase_key)
    _clear_tables(supabase, args.tables)


if __name__ == "__main__":
    main()
