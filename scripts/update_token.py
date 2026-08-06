#!/usr/bin/env python3
import os
import re
from pathlib import Path

def main():
    env_path = Path("/Users/adityahimawan/Development/idx-realtime-feed/.env")
    if not env_path.exists():
        print(f"❌ .env file not found at {env_path}")
        return

    print("🔑 Update Stockbit Bearer Token")
    new_token = input("Paste new Stockbit Bearer Token and press Enter:\n").strip()
    
    if not new_token:
        print("❌ Token cannot be empty. Aborted.")
        return

    content = env_path.read_text()
    
    # Check if STOCKBIT_BEARER_TOKEN already exists in .env
    token_pattern = re.compile(r"^STOCKBIT_BEARER_TOKEN=.*$", re.MULTILINE)
    
    if token_pattern.search(content):
        # Replace existing token
        new_content = token_pattern.sub(f"STOCKBIT_BEARER_TOKEN={new_token}", content)
    else:
        # Append new token at the end
        new_content = content + f"\nSTOCKBIT_BEARER_TOKEN={new_token}\n"

    env_path.write_text(new_content)
    print("✅ .env updated successfully with the new STOCKBIT_BEARER_TOKEN!")

if __name__ == "__main__":
    main()
