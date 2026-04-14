import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

class PromptLoader:
    """Safely loads and validates clinical prompts at startup"""
    
    def __init__(self, prompts_dir: str):
        self.prompts_dir = Path(prompts_dir)
        self._rose_prompt: Optional[str] = None
        self._clinical_prompt: Optional[str] = None
        self._load_prompts()
    
    def _load_prompts(self):
        """Load prompts with safety validation"""
        # Critical: Append structured output instruction to ROSE prompt
        # This enables reliable parsing of LLM outputs while preserving clinical tone
        json_instruction = """
        
IMPORTANT: Your response MUST be valid JSON with this exact structure:
{
  "patient_message": "Your empathetic, conversational response to the patient (in English)",
  "care_routing": {
    "recommended_pathway": "doctor" | "hospital" | "pharmacist" | "home_care",
    "urgency_level": "low" | "moderate" | "high"
  },
  "emotion": {
    "label": "calm" | "empathetic" | "reassuring" | "attentive" | "concerned" | "neutral",
    "intensity": 0.0 to 1.0
  },
  "generate_clinical_summary": true | false
}
Rules:
- patient_message MUST be warm, empathetic, and follow ROSE principles
- NEVER include diagnosis, prescriptions, or medical authority language
- generate_clinical_summary=true ONLY when sufficient symptom details exist for provider handoff
- Output ONLY JSON - no additional text, markdown, or explanations
"""
        
        # Load base ROSE prompt
        rose_path = self.prompts_dir / "rose_system_prompt.txt"
        if not rose_path.exists():
            raise FileNotFoundError(f"ROSE prompt not found at {rose_path}")
        
        with open(rose_path, "r", encoding="utf-8") as f:
            base_prompt = f.read().strip()
        
        # Append structured output instruction (critical for parsing)
        self._rose_prompt = base_prompt + json_instruction
        
        # Load clinical summary prompt
        clinical_path = self.prompts_dir / "clinical_summary_prompt.txt"
        if not clinical_path.exists():
            raise FileNotFoundError(f"Clinical summary prompt not found at {clinical_path}")
        
        with open(clinical_path, "r", encoding="utf-8") as f:
            self._clinical_prompt = f.read().strip()
        
        logger.info("Prompts loaded with structured output enforcement")
    
    def get_rose_prompt(self) -> str:
        if not self._rose_prompt:
            raise RuntimeError("ROSE prompt not initialized")
        return self._rose_prompt
    
    def get_clinical_summary_prompt(self) -> str:
        if not self._clinical_prompt:
            raise RuntimeError("Clinical summary prompt not initialized")
        return self._clinical_prompt
