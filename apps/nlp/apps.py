import logging
import os

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class NlpConfig(AppConfig):
    name = "apps.nlp"
    label = "nlp"
    verbose_name = "NLP"

    def ready(self):
        """Check model availability at app startup."""
        from django.conf import settings
        
        # Check fastText model availability
        model_path = getattr(settings, "FASTTEXT_MODEL_PATH", "")
        if not model_path or not os.path.isfile(model_path):
            logger.warning(
                "fastText language detection model NOT found at '%s'. "
                "Language detection will return 'unknown'. "
                "Download the model from: https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin",
                model_path,
            )
        else:
            logger.info("✓ fastText model available at %s", model_path)

        # Check optional AfroLID model directory
        afrolid_model_path = getattr(settings, "AFROLID_MODEL_PATH", "")
        if afrolid_model_path and os.path.isdir(afrolid_model_path):
            logger.info("✓ AfroLID model directory available at %s", afrolid_model_path)
        else:
            logger.info("AfroLID fallback not configured at %s", afrolid_model_path)
