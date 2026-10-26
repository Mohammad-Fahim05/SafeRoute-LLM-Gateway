#!/usr/bin/env python3
"""CLI utility to generate and manage SafeRoute LLM Gateway client API keys."""

import argparse
import json
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings
from app.core.auth import compute_key_verifier, generate_api_key


def update_client_keys_in_env(config_entry: dict, env_path: str = ".env") -> bool:
    """Safely add or update a client entry in CLIENT_KEYS in the .env file."""
    if not os.path.exists(env_path):
        return False

    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    client_id = config_entry["client_id"]
    client_keys_line_idx = None
    existing_clients = []

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("CLIENT_KEYS=") or stripped.startswith("CLIENT_KEYS ="):
            client_keys_line_idx = idx
            val_part = stripped.split("=", 1)[1].strip()
            if (val_part.startswith("'") and val_part.endswith("'")) or (val_part.startswith('"') and val_part.endswith('"')):
                val_part = val_part[1:-1].strip()
            try:
                parsed = json.loads(val_part)
                if isinstance(parsed, list):
                    existing_clients = parsed
            except Exception:
                pass
            break

    updated = False
    new_clients = []
    for c in existing_clients:
        if c.get("client_id") == client_id:
            new_clients.append(config_entry)
            updated = True
        else:
            new_clients.append(c)
    if not updated:
        new_clients.append(config_entry)

    new_line = f"CLIENT_KEYS='{json.dumps(new_clients)}'\n"

    if client_keys_line_idx is not None:
        lines[client_keys_line_idx] = new_line
    else:
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(new_line)

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return True


def create_key(client_id: str, custom_secret: str = "", update_env: bool = False):
    """Generate a new client API key and its safe configuration entry."""
    # Ensure fresh settings load to reflect any recent .env edits
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    settings = get_settings()
    secret = custom_secret or settings.auth_secret or os.getenv("AUTH_SECRET")

    if not secret or len(secret) < 16:
        print("\n[ERROR] AUTH_SECRET is not configured or is fewer than 16 characters.")
        print("Please set AUTH_SECRET in your environment or .env file before creating keys, or pass --secret.\n")
        sys.exit(1)

    plaintext_key = generate_api_key()
    verifier = compute_key_verifier(plaintext_key, secret)

    config_entry = {
        "client_id": client_id,
        "verifier": verifier,
        "enabled": True,
    }

    if update_env:
        success = update_client_keys_in_env(config_entry)
        if success:
            print(f"\n[OK] Automatically updated CLIENT_KEYS in .env for client '{client_id}'.")

    print("\n" + "=" * 70)
    print("SafeRoute Gateway Client API Key Generated")
    print("=" * 70)
    print(f"\nClient ID: {client_id}")
    print(f"\nPlaintext API Key:\n  {plaintext_key}\n")
    print("  [!] CAUTION: This key is displayed only ONCE.")
    print("      Store this key securely in your client environment.")
    print("      SafeRoute never stores plaintext keys.")

    if not update_env:
        print("\n" + "-" * 70)
        print("Add this configuration entry to CLIENT_KEYS in your .env file:")
        print("-" * 70)
        print(json.dumps(config_entry, indent=2))
        print("\nExample .env entry:")
        print(f"CLIENT_KEYS='[{json.dumps(config_entry)}]'\n")

    print("=" * 70)
    print("How to Revoke or Disable this key:")
    print("  1. To disable temporarily: Change '\"enabled\": true' to '\"enabled\": false'")
    print("     in the CLIENT_KEYS configuration in .env.")
    print("  2. To revoke permanently: Remove this client object from CLIENT_KEYS in .env.")
    print("  3. Restart the SafeRoute gateway for configuration changes to take effect.")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="SafeRoute LLM Gateway Key Management Utility"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Generate a new gateway API key")
    create_parser.add_argument(
        "--client-id",
        required=True,
        help="Unique identifier for the client (e.g. mobile_app, dev_alice)",
    )
    create_parser.add_argument(
        "--secret",
        default="",
        help="Optional override for AUTH_SECRET (otherwise read from environment)",
    )
    create_parser.add_argument(
        "--update-env",
        action="store_true",
        help="Automatically update CLIENT_KEYS in .env with the new verifier",
    )

    args = parser.parse_args()
    if args.command == "create":
        create_key(args.client_id, args.secret, args.update_env)


if __name__ == "__main__":
    main()
