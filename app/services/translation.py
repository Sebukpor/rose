# app/services/translation.py
import logging
from typing import Optional
import argostranslate.package
import argostranslate.translate

logger = logging.getLogger(__name__)


class TranslationService:
    """Local neural translation using Argos Translate (no cloud required)"""
    
    # COMPLETE list of languages Argos actually supports (verified from package index)
    ARGOS_SUPPORTED_LANGUAGES = {
        "en", "es", "fr", "de", "it", "pt", "zh", "ja", "ko", "ar", "hi", "ru",
         "uk", "ur"
        # NOTE: "sw" (Swahili) is NOT supported by Argos Translate
    }
    
    # Languages that Gemini handles natively (including Swahili)
    GEMINI_NATIVE_LANGUAGES = {
        "en", "es", "fr", "de", "it", "pt", "zh", "ja", "ko", "ar", "hi", "ru",
        "sw",  # Swahili - Gemini handles natively!
        "nl", "pl", "tr", "vi", "th", "id", "sv", "da", "fi", "no", "cs", "el", "he", "hu"
    }
    
    def __init__(self):
        self.installed_languages = {}
        self._download_and_load_models()
        logger.info("Translation service initialized")
    
    def _download_and_load_models(self):
        """Download translation models to /tmp/argos_models"""
        argostranslate.package.update_package_index()
        available_packages = argostranslate.package.get_available_packages()
        
        # Install models for Argos-supported languages only (excluding Swahili)
        target_codes = [lang for lang in self.ARGOS_SUPPORTED_LANGUAGES if lang != "en"]
        
        installed_count = 0
        for from_code in target_codes:
            for to_code in target_codes:
                if from_code == to_code:
                    continue
                    
                pkg = next(
                    (p for p in available_packages if p.from_code == from_code and p.to_code == to_code),
                    None
                )
                
                if pkg:
                    try:
                        argostranslate.package.install_from_path(pkg.download())
                        installed_count += 1
                        logger.debug(f"Installed translation: {from_code} → {to_code}")
                    except Exception as e:
                        logger.warning(f"Failed to install {from_code}→{to_code}: {e}")
        
        self.installed_languages = {
            lang.code: lang for lang in argostranslate.translate.get_installed_languages()
        }
        
        logger.info(f"Loaded {len(self.installed_languages)} translation models ({installed_count} pairs)")
    
    def translate_to_english(self, text: str, source_lang: str) -> str:
        """
        Translate to English for LLM processing.
        
        FOR ALL LANGUAGES (except Swahili): Use Argos Translate
        FOR SWAHILI: Bypass translation - Gemini handles it natively
        """
        if not text or not source_lang:
            return text
        
        source_lang = source_lang.split("-")[0].lower()
        
        # === SWAHILI BYPASS ===
        # Swahili is NOT in Argos, but Gemini understands it natively
        if source_lang == "sw":
            logger.info("Swahili detected - bypassing Argos, passing directly to Gemini")
            return text
        
        # === STANDARD ARGOS PIPELINE FOR ALL OTHER LANGUAGES ===
        if source_lang == "en":
            return text
            
        if source_lang not in self.ARGOS_SUPPORTED_LANGUAGES:
            logger.warning(f"Language '{source_lang}' not in Argos supported list, passing as-is to Gemini")
            return text
        
        # Check if models are installed
        if source_lang not in self.installed_languages or "en" not in self.installed_languages:
            logger.warning(f"Translation model not installed for {source_lang}→en, passing as-is")
            return text
        
        try:
            # Use Argos Translate (existing behavior preserved)
            translation = self.installed_languages[source_lang].get_translation(
                self.installed_languages["en"]
            )
            result = translation.translate(text)
            logger.debug(f"Argos translated [{source_lang}→en]: '{text[:30]}...' → '{result[:30]}...'")
            return result
            
        except Exception as e:
            logger.error(f"Argos translation failed: {e}")
            return text  # Fallback to original
    
    def translate_from_english(self, text: str, target_lang: str) -> str:
        """
        Translate LLM response from English to patient's language.
        
        FOR ALL LANGUAGES (except Swahili): Use Argos Translate  
        FOR SWAHILI: Bypass translation - Gemini outputs Swahili natively
        """
        if not text or not target_lang:
            return text
        
        target_lang = target_lang.split("-")[0].lower()
        
        # === SWAHILI BYPASS ===
        # Gemini already responded in Swahili if input was Swahili
        if target_lang == "sw":
            logger.info("Swahili target - using Gemini native output (no Argos translation needed)")
            return text
        
        # === STANDARD ARGOS PIPELINE FOR ALL OTHER LANGUAGES ===
        if target_lang == "en":
            return text
            
        if target_lang not in self.ARGOS_SUPPORTED_LANGUAGES:
            logger.warning(f"Language '{target_lang}' not in Argos supported list, returning English")
            return text
        
        # Check if models are installed
        if "en" not in self.installed_languages or target_lang not in self.installed_languages:
            logger.warning(f"Translation model not installed for en→{target_lang}, returning English")
            return text
        
        try:
            # Use Argos Translate (existing behavior preserved)
            translation = self.installed_languages["en"].get_translation(
                self.installed_languages[target_lang]
            )
            result = translation.translate(text)
            
            # Clinical safety: block authority terms introduced in translation
            if self._contains_medical_authority(result, target_lang):
                logger.warning("Translation introduced authority language, using English original")
                return text
            
            logger.debug(f"Argos translated [en→{target_lang}]: '{text[:30]}...' → '{result[:30]}...'")
            return result
            
        except Exception as e:
            logger.error(f"Argos translation failed: {e}")
            return text  # Fallback to English
    
    def _contains_medical_authority(self, text: str, lang: str) -> bool:
        """Block translations that introduce diagnostic language"""
        authority_terms = {
            "es": ["diagnóstico", "receta", "debes", "tienes que", "enfermedad"],
            "fr": ["diagnostic", "ordonnance", "devez", "maladie"],
            "de": ["diagnose", "rezept", "müssen", "krankheit"],
            "it": ["diagnosi", "ricetta", "deve", "malattia"],
            "sw": ["utambuzi", "dawa", "ugonjwa", "lazima"],  # Swahili terms (for safety check)
            "zh": ["诊断", "处方", "疾病", "需要"],
            "pt": ["diagnóstico", "receita", "deve", "doença"],
            "hi": ["निदान", "पर्चा", "दवा", "आपको लेना चाहिए", "बीमारी"],
            "default": ["diagnosis", "prescription", "you have", "must take"]
        }
        
        terms = authority_terms.get(lang, authority_terms["default"])
        lower_text = text.lower()
        return any(term in lower_text for term in terms)
    
    def should_translate(self, lang_code: str) -> bool:
        """
        Check if translation is needed for this language.
        Returns False for Swahili (Gemini native), True for others that need Argos.
        """
        if not lang_code:
            return False
        lang_code = lang_code.split("-")[0].lower()
        
        # Swahili: No translation needed (Gemini native)
        if lang_code == "sw":
            return False
        
        # English: No translation needed
        if lang_code == "en":
            return False
            
        # All other Argos-supported languages: Translation needed
        return lang_code in self.ARGOS_SUPPORTED_LANGUAGES