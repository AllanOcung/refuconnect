"""
Download required ML model files for the NLP pipeline.

Run once per environment before starting the Celery workers:

    python scripts/download_models.py

Models downloaded:
  - fastText language identification model (lid.176.bin)
  - spaCy English model (en_core_web_sm)

HuggingFace models (facebook/bart-large-mnli, cardiffnlp/twitter-xlm-roberta-base-sentiment)
are downloaded automatically by the transformers library on first use and cached in the
directory set by HUGGINGFACE_CACHE_DIR (default: models/huggingface/).
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models"
FASTTEXT_DIR = MODELS_DIR / "fasttext"
FASTTEXT_MODEL_PATH = FASTTEXT_DIR / "lid.176.bin"

FASTTEXT_DOWNLOAD_URL = (
    "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin"
)


def _progress_hook(block_num: int, block_size: int, total_size: int) -> None:
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        mb_done = downloaded / 1_048_576
        mb_total = total_size / 1_048_576
        sys.stdout.write(f"\r  {pct:3d}%  {mb_done:.1f} / {mb_total:.1f} MB")
        sys.stdout.flush()
        if pct >= 100:
            print()


def download_fasttext_model() -> None:
    """Download the fastText language identification model."""
    if FASTTEXT_MODEL_PATH.exists():
        print(f"[fastText] Model already present at {FASTTEXT_MODEL_PATH} — skipping.")
        return

    FASTTEXT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[fastText] Downloading lid.176.bin (~128 MB) ...")
    print(f"  URL : {FASTTEXT_DOWNLOAD_URL}")
    print(f"  Dest: {FASTTEXT_MODEL_PATH}")

    tmp_path = FASTTEXT_MODEL_PATH.with_suffix(".bin.tmp")
    try:
        urllib.request.urlretrieve(FASTTEXT_DOWNLOAD_URL, tmp_path, _progress_hook)
        tmp_path.rename(FASTTEXT_MODEL_PATH)
        print(f"[fastText] Saved to {FASTTEXT_MODEL_PATH}")
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        print(f"[fastText] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


def download_spacy_model() -> None:
    """Download the spaCy English model used by LocationExtractor."""
    import subprocess

    print("[spaCy] Checking for en_core_web_sm ...")
    try:
        import spacy  # type: ignore[import]
        spacy.load("en_core_web_sm")
        print("[spaCy] en_core_web_sm already installed — skipping.")
        return
    except OSError:
        pass

    print("[spaCy] Downloading en_core_web_sm ...")
    result = subprocess.run(
        [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
        check=False,
    )
    if result.returncode != 0:
        print("[spaCy] WARNING: download failed. Location extraction via NER will be disabled.", file=sys.stderr)
    else:
        print("[spaCy] en_core_web_sm installed successfully.")


def configure_huggingface_cache() -> None:
    """Ensure HuggingFace cache directory exists and print instructions."""
    hf_cache = os.environ.get("HUGGINGFACE_CACHE_DIR", str(MODELS_DIR / "huggingface"))
    Path(hf_cache).mkdir(parents=True, exist_ok=True)
    print(
        f"[HuggingFace] Cache directory: {hf_cache}\n"
        "  Models (facebook/bart-large-mnli, cardiffnlp/twitter-xlm-roberta-base-sentiment)\n"
        "  will be downloaded automatically on first use by the transformers library."
    )


if __name__ == "__main__":
    print("=== RefuConnect NLP model downloader ===\n")
    download_fasttext_model()
    download_spacy_model()
    configure_huggingface_cache()
    print("\nDone. You can now start the Celery workers.")
