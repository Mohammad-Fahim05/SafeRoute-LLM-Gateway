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


def create_key(client_id: str, custom_secret: str = ""):
    """Generate a new client API key and its safe configuration entry."""
    settings = get_settings()
    secret = custom_secret or os.getenv("AUTH_SECRET") or settings.auth_secret

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

    print("\n" + "=" * 70)
    print("SafeRoute Gateway Client API Key Generated")
    print("=" * 70)
    print(f"\nClient ID: {client_id}")
    print(f"\nPlaintext API Key:\n  {plaintext_key}\n")
    print("  [!] CAUTION: This key is displayed only ONCE.")
    print("      Store this key securely in your client environment.")
    print("      SafeRoute never stores plaintext keys.")

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

    args = parser.parse_args()
    if args.command == "create":
        create_key(args.client_id, args.secret)


if __name__ == "__main__":
    main()
