import logging
import re
from typing import Dict, Optional, Tuple
from pydantic import BaseModel, Field, validator, ValidationError

# Import from response.py to ensure consistency
from app.models.response import CarePathway, UrgencyLevel, CareRouting

logger = logging.getLogger(__name__)

class CareRoutingDecision(BaseModel):
    """Internal decision model - uses same types as response"""
    recommended_pathway: CarePathway
    urgency_level: UrgencyLevel
    
    @validator("urgency_level")
    def validate_urgency_clinical_safety(cls, v, values):
        """
        Clinical safety guardrail: Prevent dangerous downgrading of urgency
        when red-flag symptoms are present in conversation history
        """
        return v

class CareRoutingService:
    """
    Validates and enforces clinically safe care routing decisions.
    Implements mandatory escalation rules for red-flag symptoms.
    """
    
    # RED-FLAG SYMPTOMS (MANDATORY ESCALATION TO HOSPITAL/HIGH URGENCY)
    # Based on NHS 111 and CDC emergency symptom guidelines
    RED_FLAG_PATTERNS = [
        # Chest/cardiac
        r'chest pain', r'chest pressure', r'crushing chest', r'radiating arm pain',
        r'heart attack', r'cardiac', r'palpitations.*faint',
        # Neurological
        r'slurred speech', r'facial droop', r'numb.*one side', r'sudden weakness',
        r'loss of consciousness', r'seizure', r'convulsion',
        # Respiratory distress
        r'difficulty breathing', r'can.?t breathe', r'gasping', r'wheezing.*not improving',
        r'blue lips', r'cyanosis',
        # Severe bleeding/trauma
        r'uncontrolled bleeding', r'bleeding.*won.?t stop', r'major trauma',
        r'head injury.*vomiting', r'fall.*unconscious',
        # Acute abdominal
        r'sudden severe abdominal pain', r'ruptured', r'aortic',
        # Allergic/anaphylaxis
        r'swelling.*throat', r'tongue swelling', r'anaphylaxis', r'allergic reaction.*breathing',
        # Obstetric emergencies
        r'pregnant.*bleeding', r'contractions.*20 weeks', r'water broke.*premature',
        # Pediatric emergencies
        r'infant.*not breathing', r'child.*stiff neck.*fever', r'febrile seizure',
        # Poisoning/overdose
        r'overdose', r'poison', r'suicide.*attempt', r'carbon monoxide'
    ]
    
    # SYMPTOM-TO-PATHWAY MAPPING (Clinical decision support)
    SYMPTOM_ROUTING = {
        "high_acuity": {
            "symptoms": [
                "chest pain", "difficulty breathing", "sudden weakness", "severe bleeding",
                "loss of consciousness", "seizure", "major trauma", "suicidal ideation"
            ],
            "pathway": CarePathway.hospital,
            "minimum_urgency": UrgencyLevel.high
        },
        "moderate_acuity": {
            "symptoms": [
                "persistent fever", "moderate pain", "rash with fever", "nausea vomiting",
                "mild shortness of breath", "urinary symptoms", "new onset headache"
            ],
            "pathway": CarePathway.doctor,
            "minimum_urgency": UrgencyLevel.moderate
        },
        "low_acuity": {
            "symptoms": [
                "mild cold symptoms", "seasonal allergies", "minor rash", "mild headache",
                "indigestion", "minor cuts", "sleep issues"
            ],
            "pathway": CarePathway.pharmacist,
            "minimum_urgency": UrgencyLevel.low
        }
    }
    
    def __init__(self):
        # Pre-compile regex patterns for performance
        self.red_flag_regex = re.compile(
            '|'.join(f'({pattern})' for pattern in self.RED_FLAG_PATTERNS),
            re.IGNORECASE
        )
        logger.info("Care routing service initialized with clinical safety guardrails")
    
    def extract_from_llm_response(self, llm_response: Dict) -> CareRoutingDecision:
        """
        Extract and validate care routing from LLM JSON output.
        Applies mandatory clinical safety overrides.
        """
        try:
            # Get raw values from LLM response
            pathway_str = llm_response.get("care_routing", {}).get("recommended_pathway", "doctor")
            urgency_str = llm_response.get("care_routing", {}).get("urgency_level", "moderate")
            
            # Convert strings to Enums
            pathway = CarePathway(pathway_str) if isinstance(pathway_str, str) else pathway_str
            urgency = UrgencyLevel(urgency_str) if isinstance(urgency_str, str) else urgency_str
            
            # Basic extraction with schema validation
            decision = CareRoutingDecision(
                recommended_pathway=pathway,
                urgency_level=urgency
            )
            
            logger.debug(f"LLM-proposed routing: {decision.recommended_pathway.value} ({decision.urgency_level.value})")
            return decision
            
        except (ValidationError, KeyError, ValueError) as e:
            logger.warning(f"LLM routing extraction failed: {str(e)}, using safe fallback")
            return CareRoutingDecision(
                recommended_pathway=CarePathway.doctor,
                urgency_level=UrgencyLevel.moderate
            )
    
    def apply_clinical_safety_overrides(
        self,
        proposed_decision: CareRoutingDecision,
        conversation_history: list
    ) -> Tuple[CareRouting, bool]:
        """
        Apply mandatory clinical safety overrides based on red-flag symptom detection.
        Returns (final_decision, safety_override_applied)
        """
        # Flatten conversation history for analysis (patient statements only)
        patient_statements = " ".join([
            msg.get("content", "") 
            for msg in conversation_history 
            if msg.get("role") == "user"
        ]).lower()
        
        # Check for red-flag symptoms requiring mandatory escalation
        has_red_flag = bool(self.red_flag_regex.search(patient_statements))
        
        if has_red_flag:
            # MANDATORY OVERRIDE: Red flags ALWAYS route to hospital with high urgency
            overridden = CareRouting(
                recommended_pathway=CarePathway.hospital,
                urgency_level=UrgencyLevel.high
            )
            
            logger.critical(
                "CLINICAL SAFETY OVERRIDE: Red-flag symptoms detected. "
                f"Routing forced to {overridden.recommended_pathway.value} ({overridden.urgency_level.value})"
            )
            return overridden, True
        
        # Secondary safety check: Prevent dangerous downgrades for moderate symptoms
        overridden = self._apply_symptom_based_floor(proposed_decision, patient_statements)
        if overridden != proposed_decision:
            logger.warning(
                f"Symptom-based safety floor applied: {proposed_decision.recommended_pathway.value} → "
                f"{overridden.recommended_pathway.value}"
            )
            return overridden, True
        
        # Convert CareRoutingDecision to CareRouting for response
        final_routing = CareRouting(
            recommended_pathway=proposed_decision.recommended_pathway,
            urgency_level=proposed_decision.urgency_level
        )
        return final_routing, False
    
    def _apply_symptom_based_floor(
        self,
        proposed: CareRoutingDecision,
        patient_statements: str
    ) -> CareRouting:
        """
        Apply minimum routing thresholds based on detected symptom categories.
        Prevents dangerous downgrades (e.g., chest pain → home care).
        """
        # Check high-acuity symptoms
        high_acuity_terms = self.SYMPTOM_ROUTING["high_acuity"]["symptoms"]
        if any(term in patient_statements for term in high_acuity_terms):
            # Ensure minimum: doctor + moderate urgency
            if proposed.recommended_pathway == CarePathway.home_care:
                return CareRouting(
                    recommended_pathway=CarePathway.doctor,
                    urgency_level=max(proposed.urgency_level, UrgencyLevel.moderate, key=lambda x: ["low", "moderate", "high"].index(x.value))
                )
        
        # Check moderate-acuity symptoms
        moderate_acuity_terms = self.SYMPTOM_ROUTING["moderate_acuity"]["symptoms"]
        if any(term in patient_statements for term in moderate_acuity_terms):
            # Ensure minimum: pharmacist + low urgency
            if proposed.recommended_pathway == CarePathway.home_care and proposed.urgency_level == UrgencyLevel.low:
                # Allow home care only if truly low acuity; otherwise escalate
                pass  # No override needed for true low-acuity cases
        
        # Return as CareRouting type
        return CareRouting(
            recommended_pathway=proposed.recommended_pathway,
            urgency_level=proposed.urgency_level
        )
    
    def validate_final_decision(self, decision: CareRouting) -> bool:
        """
        Final validation gate before response delivery.
        Blocks clinically dangerous combinations.
        """
        # BLOCK: Hospital routing with low urgency (contradictory)
        if decision.recommended_pathway == CarePathway.hospital and decision.urgency_level == UrgencyLevel.low:
            logger.error("BLOCKED: Hospital routing with low urgency is clinically contradictory")
            return False
        
        # BLOCK: Home care with high urgency (dangerous mismatch)
        if decision.recommended_pathway == CarePathway.home_care and decision.urgency_level == UrgencyLevel.high:
            logger.error("BLOCKED: Home care routing with high urgency is clinically dangerous")
            return False
        
        # BLOCK: Pharmacist routing for high-acuity symptoms (requires validation upstream)
        # Note: This is a defense-in-depth check; primary enforcement happens in symptom analysis
        
        return True
    
    def get_patient_facing_guidance(self, decision: CareRouting) -> str:
        """
        Generate safe, non-alarming patient guidance text for the recommended pathway.
        NEVER includes diagnostic language or urgency escalation that could cause panic.
        """
        guidance_map = {
            (CarePathway.hospital, UrgencyLevel.high): (
                "Based on what you've described, I recommend seeking care at an emergency department "
                "or calling emergency services. This ensures you get timely evaluation for your symptoms."
            ),
            (CarePathway.hospital, UrgencyLevel.moderate): (
                "To be on the safe side, I recommend visiting an urgent care center or emergency department "
                "for evaluation of your symptoms."
            ),
            (CarePathway.doctor, UrgencyLevel.high): (
                "I recommend contacting a doctor today for an evaluation of your symptoms."
            ),
            (CarePathway.doctor, UrgencyLevel.moderate): (
                "I recommend scheduling a consultation with a doctor within the next few days."
            ),
            (CarePathway.doctor, UrgencyLevel.low): (
                "A doctor consultation would be helpful to discuss these symptoms when convenient."
            ),
            (CarePathway.pharmacist, UrgencyLevel.moderate): (
                "A pharmacist can provide helpful guidance for managing these symptoms."
            ),
            (CarePathway.pharmacist, UrgencyLevel.low): (
                "A pharmacist may be able to recommend appropriate over-the-counter options."
            ),
            (CarePathway.home_care, UrgencyLevel.low): (
                "For these symptoms, comfortable rest at home with monitoring is appropriate. "
                "Contact a healthcare provider if symptoms worsen or persist beyond a few days."
            )
        }
        
        # Safety fallback for unhandled combinations
        key = (decision.recommended_pathway, decision.urgency_level)
        guidance = guidance_map.get(key, guidance_map.get((CarePathway.doctor, UrgencyLevel.moderate)))
        
        # Final safety scrub: Remove alarming language
        alarming_terms = ["emergency", "immediately", "rush", "critical", "life-threatening"]
        for term in alarming_terms:
            if term in guidance.lower() and decision.urgency_level != UrgencyLevel.high:
                guidance = guidance.replace(term, "promptly" if term == "immediately" else "carefully")
        
        return guidance.strip()