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

        # Check AfroLID fallback mode (service preferred, local model optional)
        afrolid_service_url = getattr(settings, "AFROLID_SERVICE_URL", "")
        afrolid_model_path = getattr(settings, "AFROLID_MODEL_PATH", "")
        afrolid_model_file = os.path.join(afrolid_model_path, "lid.176.bin") if afrolid_model_path else ""

        if afrolid_service_url:
            logger.info("✓ AfroLID service configured at %s", afrolid_service_url)
        elif afrolid_model_file and os.path.isfile(afrolid_model_file):
            logger.info("✓ AfroLID local model available at %s", afrolid_model_file)
        else:
            logger.info(
                "AfroLID fallback not configured (service URL empty and local model missing at %s)",
                afrolid_model_file or afrolid_model_path,
            )
