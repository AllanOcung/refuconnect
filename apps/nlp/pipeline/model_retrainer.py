"""
apps/nlp/pipeline/model_retrainer.py

Monthly batch job: fine-tunes the topic classifier and sentiment model from
NGO staff corrections logged in AuditLog.  Runs on the 1st of each month
at 03:00 UTC via Celery Beat.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from datasets import Dataset
from django.conf import settings
from sklearn.model_selection import train_test_split
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

logger = logging.getLogger(__name__)

_MIN_CORRECTIONS: int = 50
_LOOKBACK_DAYS: int = 30
_ACCURACY_GATE: float = 0.80
_BIAS_MAX_GAP: float = 0.15
_TRAIN_SPLIT: float = 0.85

_BASE_MODEL: str = getattr(settings, "NLP_BASE_MODEL", "bert-base-multilingual-cased")
_MODELS_DIR: Path = Path(getattr(settings, "MODELS_BASE_DIR", "models"))
_TOPIC_DIR: Path = _MODELS_DIR / "topic_classifier"
_SENTIMENT_DIR: Path = _MODELS_DIR / "sentiment"
_TRAINING_DATA_DIR: Path = _MODELS_DIR / "training_data"
_HF_CACHE: str = getattr(settings, "HUGGINGFACE_CACHE_DIR", "models/huggingface/")

_TRAINING_CONFIG: dict = {
    "num_train_epochs": 3,
    "learning_rate": 2e-5,
    "per_device_train_batch_size": 16,
    "per_device_eval_batch_size": 16,
}


class ModelRetrainer:
    """
    Retrains the topic classifier and sentiment model from staff corrections.

    Usage:
        retrainer = ModelRetrainer()
        retrainer.run()
    """

    def run(self) -> None:
        from apps.audit.models import AuditLog
        from apps.nlp.models import AIModelLog

        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_LOOKBACK_DAYS)

        corrections = list(
            AuditLog.objects.filter(
                action="FEEDBACK_EDITED",
                field_changed__in=["category", "sentiment", "urgency_level"],
                created_at__gte=cutoff,
            ).select_related("feedback")
        )

        if len(corrections) < _MIN_CORRECTIONS:
            logger.info(
                "ModelRetrainer: only %d corrections found (minimum %d); skipping.",
                len(corrections),
                _MIN_CORRECTIONS,
            )
            AIModelLog.objects.create(
                model_name="topic_classifier",
                version="skipped",
                deployed=False,
                notes=f"Insufficient corrections: {len(corrections)} < {_MIN_CORRECTIONS}",
            )
            return

        logger.info(
            "ModelRetrainer: found %d corrections — starting retraining.", len(corrections)
        )

        topic_samples: list[dict] = []
        sentiment_samples: list[dict] = []
        seen_ids: set[int] = set()

        for correction in corrections:
            feedback = getattr(correction, "feedback", None)
            if feedback is None or feedback.pk in seen_ids:
                continue
            seen_ids.add(feedback.pk)

            text: str = feedback.message_text_en or feedback.message_text or ""
            if not text:
                continue

            sample = {
                "text": text,
                "label": correction.new_value,
                "language": feedback.language or "unknown",
                "feedback_id": feedback.pk,
            }

            if correction.field_changed == "category":
                topic_samples.append(sample)
            elif correction.field_changed == "sentiment":
                sentiment_samples.append(sample)

        # Supplement sentiment samples with all manually reviewed records
        sentiment_samples = self._merge_reviewed_sentiment(sentiment_samples)

        topic_samples = self._merge_with_historical(topic_samples, "topic")
        sentiment_samples = self._merge_with_historical(sentiment_samples, "sentiment")

        if not topic_samples:
            logger.warning("ModelRetrainer: no topic samples after merge; aborting.")
            return

        for model_name, samples, output_dir in (
            ("topic_classifier", topic_samples, _TOPIC_DIR),
            ("sentiment", sentiment_samples, _SENTIMENT_DIR),
        ):
            if not samples:
                logger.info("ModelRetrainer: no samples for %s; skipping.", model_name)
                continue

            metrics, version, deployed = self._train_model(samples, output_dir, model_name)
            self._log_training_run(
                model_name=model_name,
                version=version,
                samples=samples,
                correction_count=len(corrections),
                metrics=metrics,
                deployed=deployed,
            )

    # ── Data preparation ──────────────────────────────────────────────────────

    @staticmethod
    def _merge_reviewed_sentiment(correction_samples: list[dict]) -> list[dict]:
        """
        Supplement correction-derived sentiment samples with all manually reviewed
        Feedback records.  Only records with ``reviewed_by`` set are included to
        ensure label quality.
        """
        from apps.feedback.models import Feedback

        reviewed = (
            Feedback.objects.filter(
                status="Processed",
                reviewed_by__isnull=False,
                sentiment__isnull=False,
                message_text_en__isnull=False,
            )
            .select_related("sentiment")
            .values("pk", "message_text_en", "sentiment__sentiment_label", "language")
        )

        existing_ids = {s["feedback_id"] for s in correction_samples}
        for r in reviewed:
            if r["pk"] in existing_ids or not r["message_text_en"]:
                continue
            correction_samples.append(
                {
                    "text": r["message_text_en"],
                    "label": r["sentiment__sentiment_label"],
                    "language": r["language"] or "unknown",
                    "feedback_id": r["pk"],
                }
            )

        return correction_samples

    # ── Training ──────────────────────────────────────────────────────────────

    def _train_model(
        self, samples: list[dict], output_dir: Path, model_name: str
    ) -> tuple[dict, str, bool]:
        """Fine-tune a sequence classification model. Returns (metrics, version, deployed)."""
        all_labels: list[str] = sorted({s["label"] for s in samples})
        label2id: dict[str, int] = {label: i for i, label in enumerate(all_labels)}

        texts = [s["text"] for s in samples]
        labels = [label2id[s["label"]] for s in samples]
        language_groups = [s["language"] for s in samples]

        label_counts = Counter(labels)
        stratify = labels if min(label_counts.values()) >= 2 else None
        if stratify is None:
            logger.warning(
                "ModelRetrainer: some %s classes have fewer than 2 samples; "
                "falling back to non-stratified split.",
                model_name,
            )

        train_texts, val_texts, train_labels, val_labels, train_langs, val_langs = (
            train_test_split(
                texts,
                labels,
                language_groups,
                test_size=1 - _TRAIN_SPLIT,
                random_state=42,
                stratify=stratify,
            )
        )

        tokenizer = AutoTokenizer.from_pretrained(_BASE_MODEL, cache_dir=_HF_CACHE)
        model = AutoModelForSequenceClassification.from_pretrained(
            _BASE_MODEL,
            num_labels=len(all_labels),
            cache_dir=_HF_CACHE,
        )

        def tokenise(batch: dict) -> dict:
            return tokenizer(
                batch["text"], truncation=True, padding="max_length", max_length=128
            )

        train_ds = Dataset.from_dict(
            {"text": train_texts, "label": train_labels}
        ).map(tokenise, batched=True)

        val_ds = Dataset.from_dict(
            {"text": val_texts, "label": val_labels}
        ).map(tokenise, batched=True)

        version = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        versioned_dir = output_dir / f"v{version}"
        versioned_dir.mkdir(parents=True, exist_ok=True)

        training_args = TrainingArguments(
            output_dir=str(versioned_dir),
            num_train_epochs=_TRAINING_CONFIG["num_train_epochs"],
            learning_rate=_TRAINING_CONFIG["learning_rate"],
            per_device_train_batch_size=_TRAINING_CONFIG["per_device_train_batch_size"],
            per_device_eval_batch_size=_TRAINING_CONFIG["per_device_eval_batch_size"],
            eval_strategy="epoch",
            save_strategy="epoch",
            load_best_model_at_end=True,
            report_to="none",
        )

        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_ds,
            eval_dataset=val_ds,
        )
        trainer.train()

        predictions = trainer.predict(val_ds)
        pred_labels: list[int] = predictions.predictions.argmax(axis=-1).tolist()

        metrics = self._compute_accuracy_by_group(val_labels, pred_labels, val_langs)
        metrics["train_size"] = len(train_texts)
        metrics["val_size"] = len(val_texts)
        metrics["bias_results"] = self._bias_test(metrics)

        english_acc: float = metrics.get("accuracy_english", 0.0)
        deployed = english_acc >= _ACCURACY_GATE

        if deployed:
            symlink = output_dir / "current"
            if symlink.is_symlink():
                symlink.unlink()
            symlink.symlink_to(versioned_dir.resolve())
            logger.info(
                "ModelRetrainer: deployed %s v%s (English acc=%.2f).",
                model_name,
                version,
                english_acc,
            )
            metrics["notes"] = f"Deployed. English accuracy={english_acc:.2f}"
        else:
            logger.warning(
                "ModelRetrainer: did NOT deploy %s v%s (English acc=%.2f < gate=%.2f).",
                model_name,
                version,
                english_acc,
                _ACCURACY_GATE,
            )
            metrics["notes"] = (
                f"Not deployed. English accuracy={english_acc:.2f} < gate={_ACCURACY_GATE}"
            )

        return metrics, version, deployed

    # ── Logging ───────────────────────────────────────────────────────────────

    @staticmethod
    def _log_training_run(
        *,
        model_name: str,
        version: str,
        samples: list[dict],
        correction_count: int,
        metrics: dict,
        deployed: bool,
    ) -> None:
        from apps.nlp.models import AIModelLog

        lang_counts = Counter(s.get("language", "unknown") for s in samples)
        summary = (
            f"Trained on {len(samples)} samples. "
            f"Language distribution: {dict(lang_counts)}."
        )

        AIModelLog.objects.create(
            model_name=model_name,
            version=version,
            deployed=deployed,
            accuracy_english=metrics.get("accuracy_english"),
            accuracy_swahili=metrics.get("accuracy_swahili"),
            accuracy_other=metrics.get("accuracy_other"),
            training_samples=metrics.get("train_size", 0),
            validation_samples=metrics.get("val_size", 0),
            correction_records_used=correction_count,
            bias_test_results=metrics.get("bias_results", {}),
            training_data_summary=summary,
            notes=metrics.get("notes", ""),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _compute_accuracy_by_group(
        self,
        true_labels: list[int],
        pred_labels: list[int],
        language_groups: list[str],
    ) -> dict:
        group_correct: dict[str, list[int]] = {}
        for true, pred, lang in zip(true_labels, pred_labels, language_groups):
            group = "english" if lang == "en" else "swahili" if lang == "sw" else "other"
            group_correct.setdefault(group, []).append(int(true == pred))

        return {
            f"accuracy_{group}": sum(correct) / len(correct)
            for group, correct in group_correct.items()
        }

    def _bias_test(self, metrics: dict) -> dict:
        accuracies = {
            g: metrics[f"accuracy_{g}"]
            for g in ("english", "swahili", "other")
            if f"accuracy_{g}" in metrics
        }
        group_names = list(accuracies)
        bias_flags: list[str] = []

        for i, g1 in enumerate(group_names):
            for g2 in group_names[i + 1:]:
                gap = abs(accuracies[g1] - accuracies[g2])
                if gap > _BIAS_MAX_GAP:
                    msg = (
                        f"Bias detected: {g1} acc={accuracies[g1]:.2f} vs "
                        f"{g2} acc={accuracies[g2]:.2f} — gap={gap:.2f} > {_BIAS_MAX_GAP}"
                    )
                    logger.critical("ModelRetrainer: %s", msg)
                    bias_flags.append(msg)

        return {"flags": bias_flags, "accuracies": accuracies}

    def _merge_with_historical(
        self, new_samples: list[dict], prefix: str
    ) -> list[dict]:
        """Merge new corrections with persisted training data, deduplicating by feedback_id."""
        _TRAINING_DATA_DIR.mkdir(parents=True, exist_ok=True)
        historical_file = _TRAINING_DATA_DIR / f"{prefix}_training.jsonl"

        existing: dict[int, dict] = {}
        if historical_file.exists():
            with historical_file.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        existing[rec["feedback_id"]] = rec
                    except (json.JSONDecodeError, KeyError):
                        logger.warning(
                            "ModelRetrainer: skipping malformed line in %s.", historical_file
                        )

        for sample in new_samples:
            existing[sample["feedback_id"]] = sample

        merged = list(existing.values())

        with historical_file.open("w") as f:
            for rec in merged:
                f.write(json.dumps(rec) + "\n")

        logger.info(
            "ModelRetrainer: %d total %s samples after merge.", len(merged), prefix
        )
        return merged