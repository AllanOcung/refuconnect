#!/usr/bin/env python
"""
scripts/download_models.py

Downloads all required model files for the RefuConnect NLP subsystem.
Run once per environment before starting workers:

    python scripts/download_models.py

Models downloaded:
  - fastText lid.176.bin  (language detection)
  - spaCy en_core_web_sm  (NER for location extraction)
  - HuggingFace models are cached automatically on first use via the
    HUGGINGFACE_CACHE_DIR environment variable.

The models/ directory is in .gitignore and must never be committed.
"""
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

FASTTEXT_URL = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin"
FASTTEXT_DEST = Path(os.getenv("FASTTEXT_MODEL_PATH", "models/fasttext/lid.176.bin"))


def download_fasttext() -> None:
    if FASTTEXT_DEST.exists():
        print(f"[fasttext] Already exists: {FASTTEXT_DEST}")
        return

    FASTTEXT_DEST.parent.mkdir(parents=True, exist_ok=True)
    print(f"[fasttext] Downloading {FASTTEXT_URL} → {FASTTEXT_DEST} ...")

    def _progress(block_count, block_size, total_size):
        downloaded = block_count * block_size
        pct = min(100, downloaded * 100 // total_size) if total_size > 0 else 0
        print(f"\r  {pct}%", end="", flush=True)

    urllib.request.urlretrieve(FASTTEXT_URL, FASTTEXT_DEST, reporthook=_progress)
    print("\n[fasttext] Done.")


def download_spacy_model() -> None:
    print("[spaCy] Checking en_core_web_sm ...")
    try:
        import spacy
        spacy.load("en_core_web_sm")
        print("[spaCy] Already installed.")
    except OSError:
        print("[spaCy] Downloading en_core_web_sm ...")
        subprocess.check_call(
            [sys.executable, "-m", "spacy", "download", "en_core_web_sm"]
        )
        print("[spaCy] Done.")


def ensure_gitignore() -> None:
    """Ensure models/ is in .gitignore."""
    gitignore = Path(".gitignore")
    entry = "models/"
    if gitignore.exists():
        content = gitignore.read_text()
        if entry not in content:
            gitignore.write_text(content + f"\n{entry}\n")
            print(f"[.gitignore] Added '{entry}'.")
    else:
        gitignore.write_text(f"{entry}\n")
        print(f"[.gitignore] Created with '{entry}'.")


if __name__ == "__main__":
    ensure_gitignore()
    download_fasttext()
    download_spacy_model()
    print("\nAll models ready. You can now start Celery workers.")
