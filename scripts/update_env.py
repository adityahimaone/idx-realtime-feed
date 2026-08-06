#!/usr/bin/env python3
"""Update .env to point to new spreadsheet."""
import re
from pathlib import Path

env_path = Path('/Users/adityahimawan/Development/idx-realtime-feed/.env')
content = env_path.read_text()

old_id = '1wr2f6drQBqBUxikdJqSp1YVPaHF13qX0V3c7p4hkw5U'
new_id = '1vOMj5p-X1GAZEAd4Hp_RoSgYtauBiCKF9RW7GRHVxHM'

content = content.replace(f'MARKET_ALPHA_SPREADSHEET_ID={old_id}', f'MARKET_ALPHA_SPREADSHEET_ID={new_id}')

env_path.write_text(content)
print("=== .env UPDATED ===")

# Verify
for line in content.splitlines():
    if 'MARKET_ALPHA' in line or 'SPREADSHEET' in line:
        print(line)
