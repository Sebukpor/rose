# app/utils/language_detect.py
import logging
from typing import Tuple, Optional
from google.cloud import translate_v2 as translate
from google.oauth2 import service_account
from core.config import get_settings

logger = logging.getLogger(__name__)

class LanguageDetectionService:
    """
    Lightweight language detection using Google Translate API.
    Used to route inputs through correct translation pipelines.
    
    Clinical Safety Notes:
    - Only detects base language (e.g., 'es' not 'es-ES')
    - Falls back to English on failure to prevent pipeline breakage
    - Never exposes raw detection confidence to frontend
    """

    def __init__(self):
        settings = get_settings()
        creds = service_account.Credentials.from_service_account_info(
            settings.google_credentials_dict
        )
        self.client = translate.Client(credentials=creds)
        logger.info("Language detection service initialized")

    def detect_language(self, text: str) -> Tuple[str, float]:
        """
        Detect the dominant language of input text.
        
        Returns:
            (language_code: str, confidence: float)
            
        Safety behavior:
            - On error → returns ('en', 0.0)
            - Strips region codes (e.g., 'es-ES' → 'es')
            - Enforces minimum 3-character input
        """
        if not isinstance(text, str) or len(text.strip()) < 3:
            logger.debug("Input too short for language detection; defaulting to 'en'")
            return "en", 0.0

        try:
            detection = self.client.detect_language(text)
            lang_code = detection.get("language", "en")
            confidence = float(detection.get("confidence", 0.0))

            # Normalize to base language (strip region)
            base_lang = lang_code.split("-")[0].lower()

            # Validate against known supported set (from translation service)
            supported = {"en", "es", "fr", "de", "it", "pt", "zh", "ja", "ko", "ar", "hi", "ru"}
            if base_lang not in supported:
                logger.warning(f"Detected unsupported language '{base_lang}'; defaulting to 'en'")
                return "en", 0.0

            logger.debug(f"Detected language: {base_lang} (confidence: {confidence:.2f})")
            return base_lang, confidence

        except Exception as e:
            logger.error(f"Language detection failed: {str(e)}")
            return "en", 0.0