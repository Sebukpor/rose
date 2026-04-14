import logging
import re
from typing import List, Optional, Dict
from app.core.config import get_settings
from app.services.llm_gemini import GeminiService
from app.core.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)
settings = get_settings()


class ClinicalSummaryService:
    """
    Orchestrates clinical summary generation with multi-layer safety validation.
    Summaries are STRICTLY for provider handoff - NEVER shown to patients.
    """
    
    def __init__(self, gemini_service: GeminiService, prompt_loader: PromptLoader):
        self.gemini = gemini_service
        self.prompt_loader = prompt_loader
        self.symptom_keywords = [
            "pain", "ache", "hurt", "fever", "temperature", "chill", "sweat",
            "rash", "redness", "swelling", "edema", "nausea", "vomit", "diarrhea",
            "dizzy", "lightheaded", "faint", "weak", "fatigue", "tired",
            "cough", "breath", "shortness", "wheeze", "chest", "heart",
            "bleed", "bleeding", "bruise", "numb", "tingle", "headache",
            "duration", "since", "started", "worsen", "better", "severity"
        ]
        self.blocked_phrases = [
            "diagnosis", "diagnose", "prescribe", "prescription", "medication",
            "treatment", "treat", "cure", "should take", "must take",
            "you have", "likely have", "probably have", "definitely",
            "emergency", "911", "immediately", "right now", "rush"
        ]
    
    def should_generate(self, conversation_history: List[Dict], min_symptoms: int = None) -> bool:
        """Determines if sufficient clinical data exists for summary generation."""
        if min_symptoms is None:
            min_symptoms = settings.CLINICAL_SUMMARY_MIN_SYMPTOMS
        
        symptom_count = 0
        for msg in conversation_history:
            if msg.get("role") != "user":
                continue
            
            content = msg.get("content", "").lower()
            if any(kw in content for kw in self.symptom_keywords):
                symptom_count += 1
        
        sufficient = symptom_count >= min_symptoms
        logger.info(f"Symptom count: {symptom_count}/{min_symptoms} → Summary generation: {'YES' if sufficient else 'NO'}")
        return sufficient
    
    async def generate(self, conversation_history: List[Dict]) -> Optional[str]:
        """
        Generates provider-facing clinical summary with multi-stage safety validation.
        NOW ASYNC to support cached LLM calls.
        """
        if not self.should_generate(conversation_history):
            logger.info("Skipping clinical summary: insufficient symptom data")
            return None
        
        # Build conversation history string
        history_str = self._format_conversation_history(conversation_history)
        
        # Generate raw summary - NOW AWAITED
        prompt = self.prompt_loader.get_clinical_summary_prompt()
        
        # Check if any images were in the conversation
        include_image_observations = any(
            "image_data" in msg and msg["image_data"] 
            for msg in conversation_history
        )
        
        # Call async method with await
        raw_summary = await self.gemini.generate_clinical_summary(
            prompt, 
            [{"role": "user", "content": history_str}],
            include_image_observations=include_image_observations
        )
        
        if not raw_summary:
            logger.info("Clinical summary generation returned None")
            return None
        
        # Safety validation - fix the .upper() call issue
        if isinstance(raw_summary, str):
            if "INSUFFICIENT_DATA" in raw_summary.upper() or len(raw_summary) < 20:
                logger.info("Clinical summary blocked: insufficient data after LLM generation")
                return None
        else:
            logger.error(f"Unexpected summary type: {type(raw_summary)}")
            return None
        
        # Apply multi-stage safety validation
        validated_summary = self._validate_summary(raw_summary, conversation_history)
        
        if validated_summary:
            logger.info("Clinical summary validated and approved for provider handoff")
            return validated_summary
        else:
            logger.warning("Clinical summary rejected by safety validation")
            return None
    
    def _format_conversation_history(self, history: List[Dict]) -> str:
        """Formats history for clinical summary prompt with safety annotations"""
        formatted = []
        for i, msg in enumerate(history):
            role = "PATIENT" if msg.get("role") == "user" else "ROSE"
            content = msg.get("content", "").strip()
            
            # Anonymize potentially identifying information
            content = self._scrub_pii(content)
            
            formatted.append(f"[TURN {i+1} - {role}]: {content}")
        
        return "\n".join(formatted)
    
    def _scrub_pii(self, text: str) -> str:
        """Basic PII scrubbing for audit safety"""
        patterns = [
            r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',
            r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',
            r'\b\d{1,5}\s+\w+\s+\w+\b'
        ]
        
        scrubbed = text
        for pattern in patterns:
            scrubbed = re.sub(pattern, "[REDACTED]", scrubbed)
        
        return scrubbed
    
    def _validate_summary(self, summary: str, conversation_history: List[Dict]) -> Optional[str]:
        """Multi-stage safety validation for clinical summaries"""
        # Stage 1: Block prohibited phrases
        summary_lower = summary.lower()
        for phrase in self.blocked_phrases:
            if phrase in summary_lower:
                logger.warning(f"Summary blocked: contains prohibited phrase '{phrase}'")
                return None
        
        # Stage 2: Verify factual grounding
        patient_statements = " ".join([
            msg.get("content", "") for msg in conversation_history if msg.get("role") == "user"
        ]).lower()
        
        symptom_claims = []
        for kw in self.symptom_keywords:
            if kw in summary_lower and kw not in patient_statements:
                symptom_claims.append(kw)
        
        if symptom_claims:
            logger.warning(f"Summary blocked: contains unverified symptoms {symptom_claims}")
            return None
        
        # Stage 3: Block speculative language
        speculative_terms = ["might", "could be", "possibly", "probably", "appears to be", "seems like"]
        if any(term in summary_lower for term in speculative_terms):
            logger.warning("Summary blocked: contains speculative language")
            return None
        
        # Stage 4: Professional tone validation
        emotional_phrases = ["worried", "scared", "anxious", "frightened", "distressed", "upset"]
        if any(phrase in summary_lower for phrase in emotional_phrases):
            logger.warning("Summary blocked: contains emotional patient description")
            return None
        
        # Stage 5: Minimum length validation
        if len(summary.strip()) < 30:
            logger.warning("Summary blocked: too short for clinical utility")
            return None
        
        return summary.strip()