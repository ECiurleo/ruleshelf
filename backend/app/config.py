"""Runtime configuration.

Everything is driven by environment variables so the container can be pointed at
a volume without code changes.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Ruleshelf"
APP_VERSION = "0.11.0"

BASE_DIR = Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    explicit = os.environ.get("RULESHELF_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    # Running inside the published container: the image declares /data.
    if Path("/data").is_dir() and os.access("/data", os.W_OK):
        return Path("/data")
    # Local development fallback: ./data next to the backend package.
    return BASE_DIR / "data"


DATA_DIR = _data_dir()
FILES_DIR = DATA_DIR / "files"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"
DB_PATH = DATA_DIR / "ruleshelf.db"

IN_CONTAINER = Path("/.dockerenv").exists()


def _ollama_url() -> str:
    """Sensible default so a host-installed Ollama can be reached from Docker."""
    explicit = os.environ.get("RULESHELF_OLLAMA_URL")
    if explicit:
        return explicit.rstrip("/")
    if IN_CONTAINER:
        return "http://host.docker.internal:11434"
    return "http://localhost:11434"


OLLAMA_DEFAULT_URL = _ollama_url()

# Largest upload accepted per file. Override for very large scanned books.
MAX_UPLOAD_BYTES = int(os.environ.get("RULESHELF_MAX_UPLOAD_MB", "512")) * 1024 * 1024

# Host/port used by `python -m app` and the container entrypoint.
HOST = os.environ.get("RULESHELF_HOST", "0.0.0.0")
PORT = int(os.environ.get("RULESHELF_PORT", "8000"))

CHUNK_SIZE = int(os.environ.get("RULESHELF_CHUNK_SIZE", "1100"))
CHUNK_OVERLAP = int(os.environ.get("RULESHELF_CHUNK_OVERLAP", "160"))

FILES_DIR.mkdir(parents=True, exist_ok=True)
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
