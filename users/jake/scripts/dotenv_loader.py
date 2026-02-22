"""
Minimal .env loader — stdlib only, no pip required.
Call load_dotenv() at the top of any script to populate os.environ
from the workspace .env file.
"""
import os
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent
ENV_FILE = WORKSPACE / ".env"


def load_dotenv():
    if not ENV_FILE.exists():
        return
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:  # don't override existing env vars
                os.environ[key] = value
