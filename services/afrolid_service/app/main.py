from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("afrolid_service")

app = FastAPI(title="AfroLID microservice")

# module-level model placeholder (set on startup)
_model: Any | None = None


class DetectRequest(BaseModel):
    text: str


class DetectResponse(BaseModel):
    language: str
    confidence: float
    needs_language_review: bool = False
    top_predictions: list[list[Any]] = []


@app.get("/")
def root():
    return {"status": "ok"}


@app.on_event("startup")
async def load_model():
    global _model
    import os
    import fasttext

    model_path = os.environ.get("AFROLID_MODEL_PATH", "/app/models/afrolid")
    model_file = os.path.join(model_path, "lid.176.bin")
    
    print(f"[STARTUP] Checking model at {model_file}")
    logger.info("Checking model at %s", model_file)
    
    if not os.path.isfile(model_file):
        print(f"[STARTUP] Model file NOT FOUND at {model_file}")
        logger.warning("fasttext model not found at %s", model_file)
        _model = None
        return
    
    try:
        print(f"[STARTUP] Loading fasttext model from {model_file}")
        fasttext.FastText.eprint = lambda x: None
        _model = fasttext.load_model(model_file)
        print(f"[STARTUP] Model loaded successfully, type={type(_model)}")
        logger.info("fasttext model loaded from %s", model_file)
    except Exception as exc:
        print(f"[STARTUP] ERROR loading model: {exc}")
        logger.exception("Failed to load fallback model: %s", exc)
        _model = None


@app.post("/detect", response_model=DetectResponse)
def detect(req: DetectRequest):
    text = req.text or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="empty text")

    if _model is None:
        print("[DETECT] ERROR: _model is None!")
        raise HTTPException(status_code=503, detail="fallback model unavailable")

    print(f"[DETECT] Processing text: {text[:50]}...")
    try:
        print(f"[DETECT] Calling _model.predict...")
        labels, probs = _model.predict(text, k=3)
        print(f"[DETECT] Got labels={labels}, probs={probs}")
    except Exception as e:
        print(f"[DETECT] Exception during predict: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        logger.exception("classification failed")
        raise HTTPException(status_code=500, detail="classification failed")

    preds = []
    best_lang = "unknown"
    best_conf = 0.0
    for label, prob in zip(labels, probs):
        lang = label.replace("__label__", "")
        score = float(prob)
        preds.append([lang, round(score, 4)])
        if score > best_conf:
            best_conf = score
            best_lang = lang

    print(f"[DETECT] Returning language={best_lang}, confidence={best_conf}")
    return DetectResponse(language=best_lang, confidence=round(best_conf,4), needs_language_review=False, top_predictions=preds)
