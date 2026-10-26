#!/usr/bin/env python3
"""CLI utility to export SafeRoute LLM Gateway request and usage records to CSV."""

import argparse
import os
import sys
from pathlib import Path

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import db_service, init_db


def export_csv(client_id: str, output_file: str) -> None:
    """Query database records and write clean CSV export."""
    init_db()

    target_client = client_id if client_id != "all" else None
    csv_data = db_service.export_records_csv(client_id=target_client)

    out_path = Path(output_file).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write(csv_data)

    print("\n" + "=" * 60)
    print("SafeRoute Usage Export Complete")
    print("=" * 60)
    print(f"Scope: {'All clients' if not target_client else f'Client: {target_client}'}")
    print(f"Export Destination: {out_path}")
    print("Security: Raw prompts, secrets, and API keys are strictly excluded.")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Export SafeRoute Gateway usage and request records to CSV"
    )
    parser.add_argument(
        "--client-id",
        default="all",
        help="Filter export by specific client ID, or 'all' (default: all)",
    )
    parser.add_argument(
        "--output",
        default="data/usage_export.csv",
        help="Destination path for CSV file (default: data/usage_export.csv)",
    )

    args = parser.parse_args()
    export_csv(args.client_id, args.output)


if __name__ == "__main__":
    main()
