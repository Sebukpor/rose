import logging
from typing import Dict
from app.models.response import EmotionMetadata

logger = logging.getLogger(__name__)

class EmotionValidationService:
    """
    Validates and normalizes LLM-generated emotions against clinical safety boundaries.
    Prevents dangerous emotional states that could escalate patient anxiety.
    """
    
    # Clinically validated emotion boundaries (ROSE protocol v1.2)
    SAFE_EMOTIONS = {
        "calm": {"min_intensity": 0.3, "max_intensity": 0.8, "description": "Steady, reassuring presence"},
        "empathetic": {"min_intensity": 0.5, "max_intensity": 0.9, "description": "Warm understanding"},
        "reassuring": {"min_intensity": 0.4, "max_intensity": 0.85, "description": "Confident comfort"},
        "attentive": {"min_intensity": 0.6, "max_intensity": 0.95, "description": "Focused engagement"},
        "concerned": {"min_intensity": 0.5, "max_intensity": 0.8, "description": "Appropriate clinical concern (NEVER alarm)"},  # Critical safety bound
        "neutral": {"min_intensity": 0.2, "max_intensity": 0.6, "description": "Professional baseline"}
    }
    
    DANGEROUS_EMOTIONS = {
        "alarmed", "panicked", "urgent", "frightened", "terrified", "desperate",
        "overwhelmed", "hysterical", "frantic", "emergency"  # Blocked terms
    }
    
    def validate(self, emotion_input: Dict) -> EmotionMetadata:
        """
        Validates and sanitizes emotion metadata against clinical safety boundaries.
        Returns normalized EmotionMetadata or safe fallback.
        """
        try:
            # Extract and normalize inputs
            label = str(emotion_input.get("label", "calm")).lower().strip()
            intensity = float(emotion_input.get("intensity", 0.5))
            
            # Block dangerous emotion labels
            if any(danger in label for danger in self.DANGEROUS_EMOTIONS):
                logger.warning(f"Blocked dangerous emotion label: '{label}'")
                return self._safe_fallback_emotion("concerned", 0.6)
            
            # Validate against safe emotions registry
            if label not in self.SAFE_EMOTIONS:
                logger.warning(f"Unknown emotion label '{label}', using fallback")
                return self._safe_fallback_emotion("attentive", 0.7)
            
            # Clamp intensity to clinically safe ranges
            bounds = self.SAFE_EMOTIONS[label]
            clamped_intensity = max(bounds["min_intensity"], min(bounds["max_intensity"], intensity))
            
            # Special safety rule: "concerned" must never exceed 0.8 intensity (prevents alarm escalation)
            if label == "concerned" and clamped_intensity > 0.8:
                clamped_intensity = 0.75
                logger.warning("Clamped 'concerned' intensity to safe maximum (0.75)")
            
            validated = EmotionMetadata(
                label=label,
                intensity=round(clamped_intensity, 2)
            )
            
            logger.debug(f"Validated emotion: {label} @ {validated.intensity}")
            return validated
            
        except Exception as e:
            logger.error(f"Emotion validation failed: {str(e)}")
            return self._safe_fallback_emotion("calm", 0.6)
    
    def _safe_fallback_emotion(self, label: str, intensity: float) -> EmotionMetadata:
        """Returns clinically safe fallback emotion when validation fails"""
        # Ensure fallback is always within safe bounds
        bounds = self.SAFE_EMOTIONS.get(label, self.SAFE_EMOTIONS["calm"])
        safe_intensity = max(bounds["min_intensity"], min(bounds["max_intensity"], intensity))
        
        logger.warning(f"Using safe emotion fallback: {label} @ {safe_intensity}")
        return EmotionMetadata(label=label, intensity=round(safe_intensity, 2))