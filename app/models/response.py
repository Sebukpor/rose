from pydantic import BaseModel, Field, validator
from typing import Optional, Literal  # ADD Literal here
from datetime import datetime
from enum import Enum

# === ENUMS FOR CARE ROUTING ===
class CarePathway(str, Enum):
    doctor = "doctor"
    hospital = "hospital"
    pharmacist = "pharmacist"
    home_care = "home_care"

class UrgencyLevel(str, Enum):
    low = "low"
    moderate = "moderate"
    high = "high"

# === PATIENT-FACING RESPONSES ===
class EmotionMetadata(BaseModel):
    label: Literal["calm", "empathetic", "reassuring", "attentive", "concerned", "neutral"]
    intensity: float = Field(..., ge=0.0, le=1.0)

class AudioResponse(BaseModel):
    encoding: Literal["base64"] = "base64"  # FIX: Use Literal instead of const=True
    data: str  # Base64 string
    sample_rate: int = Field(24000, ge=8000, le=48000)
    mime_type: Literal["audio/wav", "audio/mpeg", "audio/ogg"]
    duration_ms: int = Field(..., ge=0)

class PatientResponse(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    audio: Optional[AudioResponse] = None
    emotion: EmotionMetadata

# === PROVIDER-FACING METADATA ===
class CareRouting(BaseModel):
    recommended_pathway: CarePathway  # Changed from Literal to Enum
    urgency_level: UrgencyLevel       # Changed from Literal to Enum

class ClinicalSummary(BaseModel):
    available: bool
    summary_text: Optional[str] = None  # NULL if not available
    generated_at: Optional[datetime] = None

# === FULL RESPONSE ===
class TriageResponse(BaseModel):
    patient_response: PatientResponse
    care_routing: CareRouting
    clinical_summary: ClinicalSummary
    timing: dict = Field(default_factory=dict)  # e.g., {"stt_ms": 210, "llm_ms": 1200}
    metadata: dict = Field(
        default_factory=lambda: {
            "language_detected": "en",
            "audio_mode": False,
            "translation_applied": False,
            "safety_protocol": "ROSE_v1.0"
        }
    )
    # 🔹 NEW: Token usage tracking
    token_usage: Optional[dict] = Field(
        default=None,
        description="Token consumption breakdown for billing/monitoring"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)

# === ERROR HANDLING ===
class ErrorResponse(BaseModel):
    error: Literal["client_error", "server_error", "clinical_safety"]
    message: str
    suggestion: str
    reference_id: Optional[str] = None