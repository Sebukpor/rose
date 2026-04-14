from fastapi import APIRouter, HTTPException, Depends, status, Header
from fastapi.responses import JSONResponse, StreamingResponse
import base64
import time
import logging
import json
import uuid
from typing import List, Dict, Optional, Tuple, AsyncGenerator
from functools import lru_cache

# Fix imports to use absolute imports from project root
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.core.prompt_loader import PromptLoader
from app.models.request import TriageRequest
from app.models.response import (
    TriageResponse, 
    ClinicalSummary, 
    ErrorResponse,
    CareRouting,
    CarePathway,
    UrgencyLevel,
    EmotionMetadata
)
from app.services.speech_to_text import SpeechToTextService
from app.services.translation import TranslationService
from app.services.text_to_speech import TextToSpeechService
from app.services.llm_gemini import GeminiService
from app.services.emotion_engine import EmotionValidationService
from app.services.care_routing import CareRoutingService
from app.services.image_processor import MedicalImageProcessor
from app.services.gemini_cache_manager import get_cache_manager
from app.services.usage_limiter import QuotaExceededError
from app.api.dependencies import get_current_user
from app.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter()


class ServiceContainer:
    """
    Singleton container for services to prevent re-initialization on every request.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    async def initialize(self):
        if self._initialized:
            return
       
        logger.info("Initializing service container (singleton)...")
        settings = get_settings()
   
        # Initialize all services
        self.stt = SpeechToTextService()
        self.translation = TranslationService()
        self.tts = TextToSpeechService()
        self.gemini = GeminiService()
        await self.gemini.initialize()  # Initialize cache manager
        self.prompts = PromptLoader(settings.PROMPTS_DIR)
        self.emotion = EmotionValidationService()
        self.routing = CareRoutingService()
        self.image_processor = MedicalImageProcessor()
   
        self._initialized = True
        logger.info("✅✅Service container initialized successfully")

    @property
    def stt_service(self):
        return self.stt

    @property
    def translation_service(self):
        return self.translation

    @property
    def tts_service(self):
        return self.tts

    @property
    def gemini_service(self):
        return self.gemini

    @property
    def prompt_loader(self):
        return self.prompts

    @property
    def emotion_validator(self):
        return self.emotion

    @property
    def care_routing_service(self):
        return self.routing

    @property
    def image_service(self):
        return self.image_processor


# Global singleton instance
_service_container: Optional[ServiceContainer] = None

async def get_service_container() -> ServiceContainer:
    """Get or create the singleton service container"""
    global _service_container
    if _service_container is None:
        _service_container = ServiceContainer()
        await _service_container.initialize()
    return _service_container


def detect_input_language(request: TriageRequest) -> str:
    """Robust language detection for current input."""
    explicit_lang = getattr(request, 'current_input_language', None)
    if explicit_lang and explicit_lang != "en":
        return explicit_lang
    
    if request.conversation_history:
        for msg in reversed(request.conversation_history):
            if msg.role.value == "user" and msg.language and msg.language != "en":
                return msg.language
    
    return "en"


async def process_triage_request(
    request: TriageRequest,
    settings,
    svc: ServiceContainer,
    stream_mode: bool = False,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> Dict:
    """
    Core triage processing logic.
    Returns dict with response data or async generator for streaming.
    
    New parameters:
        user_id: User identifier for usage tracking (optional)
        session_id: Session identifier for usage tracking (optional)
    """
    timing = {}
    start_total = time.time()
    image_metadata = None
    multimodal_input = None
    token_usage = None
    
    # 🔹 Import usage tracking from main
    from app import main as app_main
    
    # 🔹 NEW: Check quota before processing
    if app_main.usage_limiter and user_id:
        try:
            # Estimate ~2000 tokens for typical triage call
            await app_main.usage_limiter.check_quota(user_id, tokens_needed=2000)
        except QuotaExceededError as e:
            logger.warning(f"Quota exceeded for user {user_id}")
            quota_summary = await app_main.usage_limiter.get_usage_summary(user_id)
            
            raise HTTPException(
                status_code=429,
                detail=f"Monthly token limit exceeded: {e.tokens_used}/{e.limit} tokens used. "
                       f"Current tier: {quota_summary.get('tier', 'free')}. "
                       f"Days remaining: {quota_summary.get('days_remaining', 0)}."
            )
    
    # STEP 0: VALIDATE CONVERSATION LENGTH
    if len(request.conversation_history) > settings.MAX_CONVERSATION_TURNS:
        raise HTTPException(
            status_code=400,
            detail=f"Conversation exceeds maximum turns ({settings.MAX_CONVERSATION_TURNS})"
        )
    
    # STEP 1: PROCESS INPUT
    current_text = request.current_input_text
    detected_lang = "en"
    audio_mode = False
    confidence_score = 1.0
    translation_applied = False
    include_image_in_history = False
    
    has_image = (
        request.current_input_image is not None and
        request.current_input_image.data is not None and
        request.current_input_image.data != ""
    )
    
    # IMAGE PROCESSING
    if request.current_input_type.value in ['image', 'multimodal'] and has_image:
        img_start = time.time()
        try:
            processed_b64, final_mime, img_meta = svc.image_service.process_image(
                request.current_input_image.data,
                request.current_input_image.mime_type,
                request.current_input_image.description
            )
            image_metadata = img_meta
            timing['image_processing_ms'] = int((time.time() - img_start) * 1000)
            
            text_content = request.current_input_text or "Patient provided this image for assessment."
            detected_lang = detect_input_language(request)
            
            translation_start = time.time()
            current_text_english = text_content
            if detected_lang != "en" and detected_lang in settings.argos_language_set:
                try:
                    current_text_english = svc.translation_service.translate_to_english(
                        text_content, detected_lang
                    )
                    translation_applied = True
                except Exception as e:
                    logger.error(f"Translation to English failed: {str(e)}")
            timing["translation_ms"] = int((time.time() - translation_start) * 1000)
            
            multimodal_input = {
                "text": f"[IMAGE CONTEXT]: Patient shares: '{current_text_english}'\n[CLINICAL NOTE]: Analyze image objectively. Describe visible symptoms only.",
                "image": {"data": processed_b64, "mime_type": final_mime}
            }
            include_image_in_history = True
            
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Image processing failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected image processing error: {str(e)}")
            raise HTTPException(status_code=500, detail="Image processing service unavailable")
    
    # AUDIO PROCESSING
    elif request.current_input_type.value == 'audio':
        audio_mode = True
        stt_start = time.time()
        
        if not request.current_input_audio:
            raise HTTPException(status_code=400, detail="Audio data required for audio input type")
        
        try:
            audio_bytes = base64.b64decode(request.current_input_audio)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 audio data")
        
        if len(audio_bytes) > settings.MAX_AUDIO_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Audio exceeds size limit ({len(audio_bytes) / 1e6:.1f}MB)"
            )
        
        try:
            current_text, detected_lang, confidence_score = svc.stt_service.transcribe(
                request.current_input_audio, 
                mime_type="audio/wav"
            )
            timing["stt_ms"] = int((time.time() - stt_start) * 1000)
            
            if confidence_score < 0.3:
                raise HTTPException(
                    status_code=400,
                    detail="I didn't understand that clearly. Could you describe your symptoms again?"
                )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"STT processing failed: {str(e)}")
            raise HTTPException(status_code=500, detail="Audio processing failed.")
        
        translation_start = time.time()
        current_text_english = current_text
        if detected_lang != "en" and detected_lang in settings.argos_language_set:
            try:
                current_text_english = svc.translation_service.translate_to_english(
                    current_text, detected_lang
                )
                translation_applied = True
            except Exception as e:
                logger.error(f"Translation to English failed: {str(e)}")
        timing["translation_ms"] = int((time.time() - translation_start) * 1000)
    
    # TEXT PROCESSING
    else:
        if not current_text:
            raise HTTPException(status_code=400, detail="Text input required for text input type")
        
        detected_lang = detect_input_language(request)
        
        translation_start = time.time()
        current_text_english = current_text
        if detected_lang != "en" and detected_lang in settings.argos_language_set:
            try:
                current_text_english = svc.translation_service.translate_to_english(
                    current_text, detected_lang
                )
                translation_applied = True
            except Exception as e:
                logger.error(f"Translation to English failed: {str(e)}")
        timing["translation_ms"] = int((time.time() - translation_start) * 1000)
    
    # STEP 2-3: BUILD CONVERSATION HISTORY
    history_english = []
    for msg in request.conversation_history:
        msg_content = msg.content
        msg_lang = msg.language or "en"
        
        if msg_lang != "en" and msg_lang in settings.argos_language_set:
            try:
                msg_content = svc.translation_service.translate_to_english(msg_content, msg_lang)
            except Exception as e:
                logger.warning(f"History translation failed: {e}")
        
        history_entry = {"role": msg.role.value, "content": msg_content}
        history_english.append(history_entry)
    
    current_entry = {"role": "user", "content": current_text_english}
    if include_image_in_history and multimodal_input:
        current_entry["image_data"] = multimodal_input["image"]["data"]
        current_entry["image_mime"] = multimodal_input["image"]["mime_type"]
    history_english.append(current_entry)
    
    # STEP 4: GEMINI LLM PROCESSING
    llm_start = time.time()
    system_prompt = svc.prompt_loader.get_rose_prompt()
    
    if stream_mode:
        # Return streaming generator
        return {
            "stream": _stream_response(
                svc, system_prompt, history_english, multimodal_input,
                detected_lang, translation_applied, audio_mode, confidence_score,
                timing, start_total, image_metadata, request, settings,
                user_id, session_id
            ),
            "timing": timing,
            "detected_lang": detected_lang
        }
    
    # Non-streaming mode - 🔹 UPDATED: Now extracts token usage
    try:
        llm_response, llm_duration, token_usage = await svc.gemini_service.generate_triage_response(
            system_prompt,
            history_english,
            current_multimodal_input=multimodal_input,
            use_streaming=False
        )
        timing["llm_ms"] = int(llm_duration)
        
        patient_message_english = llm_response.get("patient_message", "")
        care_routing_dict = llm_response.get("care_routing", {})
        emotion_dict = llm_response.get("emotion", {})
        generate_summary_flag = llm_response.get("generate_clinical_summary", False)
        image_analysis = llm_response.get("image_analysis")
        
    except Exception as e:
        logger.error(f"LLM processing failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Clinical reasoning temporarily unavailable")
    
    # Process response (routing, translation, etc.)
    return await _finalize_response(
        svc, patient_message_english, care_routing_dict, emotion_dict,
        generate_summary_flag, image_analysis, history_english, detected_lang,
        translation_applied, audio_mode, confidence_score, timing, start_total,
        image_metadata, request, settings, llm_response, token_usage,
        user_id, session_id
    )


async def _stream_response(
    svc: ServiceContainer,
    system_prompt: str,
    history_english: List[Dict],
    multimodal_input: Optional[Dict],
    detected_lang: str,
    translation_applied: bool,
    audio_mode: bool,
    confidence_score: float,
    timing: Dict,
    start_total: float,
    image_metadata: Optional[Dict],
    request: TriageRequest,
    settings,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> AsyncGenerator[str, None]:
    """
    Stream response chunks to the client.
    Yields SSE-formatted data.
    """
    collected_text = ""
    
    async for chunk in svc.gemini_service.generate_triage_response_stream(
        system_prompt,
        history_english,
        multimodal_input
    ):
        collected_text += chunk
        # Yield partial text for real-time display
        yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"
    
    # Parse complete response
    try:
        llm_response = json.loads(collected_text)
    except json.JSONDecodeError:
        llm_response = {
            "patient_message": collected_text,
            "care_routing": {"recommended_pathway": "doctor", "urgency_level": "moderate"},
            "emotion": {"label": "attentive", "intensity": 0.8},
            "generate_clinical_summary": False,
            "image_analysis": None
        }
    
    # Finalize and yield complete response
    final_response = await _finalize_response(
        svc,
        llm_response.get("patient_message", ""),
        llm_response.get("care_routing", {}),
        llm_response.get("emotion", {}),
        llm_response.get("generate_clinical_summary", False),
        llm_response.get("image_analysis"),
        history_english,
        detected_lang,
        translation_applied,
        audio_mode,
        confidence_score,
        timing,
        start_total,
        image_metadata,
        request,
        settings,
        llm_response,
        token_usage=None,  # Streaming doesn't track tokens separately
        user_id=user_id,
        session_id=session_id
    )
    
    yield f"data: {json.dumps({'type': 'complete', 'response': final_response})}\n\n"


async def _finalize_response(
    svc: ServiceContainer,
    patient_message_english: str,
    care_routing_dict: Dict,
    emotion_dict: Dict,
    generate_summary_flag: bool,
    image_analysis: Optional[Dict],
    history_english: List[Dict],
    detected_lang: str,
    translation_applied: bool,
    audio_mode: bool,
    confidence_score: float,
    timing: Dict,
    start_total: float,
    image_metadata: Optional[Dict],
    request: TriageRequest,
    settings,
    llm_response: Dict,
    token_usage=None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> Dict:
    """Finalize response with routing, translation, and metadata.
    
    New parameters:
        token_usage: TokenUsage object from LLM response
        user_id: User identifier for usage recording
        session_id: Session identifier for usage recording
    """
    
    # Image safety check
    if image_analysis and image_analysis.get('visual_urgency_indicators') != ['none']:
        logger.warning("Visual urgency indicators detected - applying safety floor")
        if care_routing_dict.get('recommended_pathway') == 'home_care':
            care_routing_dict['recommended_pathway'] = 'doctor'
            care_routing_dict['urgency_level'] = 'moderate'
    
    # Validate emotion
    try:
        validated_emotion = svc.emotion_validator.validate(emotion_dict)
    except Exception as e:
        logger.error(f"Emotion validation failed: {str(e)}")
        validated_emotion = EmotionMetadata(label="calm", intensity=0.6)
    
    # Extract and validate care routing
    try:
        proposed_decision = svc.care_routing_service.extract_from_llm_response(
            {"care_routing": care_routing_dict}
        )
        final_care_routing, safety_override_applied = svc.care_routing_service.apply_clinical_safety_overrides(
            proposed_decision, 
            history_english
        )
        if safety_override_applied:
            logger.critical(f"✅✅CLINICAL SAFETY OVERRIDE APPLIED")
    except Exception as e:
        logger.error(f"Care routing validation failed: {str(e)}")
        final_care_routing = CareRouting(
            recommended_pathway=CarePathway.doctor,
            urgency_level=UrgencyLevel.moderate
        )
    
    # Translate response
    response_text = patient_message_english
    if detected_lang != "en" and detected_lang in settings.argos_language_set:
        try:
            response_text = svc.translation_service.translate_from_english(
                patient_message_english, 
                detected_lang
            )
        except Exception as e:
            logger.error(f"Response translation failed: {str(e)}")
    
    # Clinical summary
    clinical_summary_obj = ClinicalSummary(available=False, summary_text=None)
    if generate_summary_flag:
        clinical_start = time.time()
        try:
            from app.services.clinical_summary import ClinicalSummaryService
            summary_service = ClinicalSummaryService(svc.gemini_service, svc.prompt_loader)
            summary_text = await summary_service.generate(history_english)
            if summary_text:
                from datetime import datetime
                clinical_summary_obj = ClinicalSummary(
                    available=True,
                    summary_text=summary_text,
                    generated_at=datetime.utcnow()
                )
                timing["clinical_summary_ms"] = int((time.time() - clinical_start) * 1000)
                logger.info("✅✅clinical summmary generated and validated")
        except Exception as e:
            logger.error(f"Clinical summary generation failed: {str(e)}")
     
    
    # Audio generation
    audio_response = None
    tts_requested = request.response_mode.value in ["audio", "both"] or audio_mode
    
    if tts_requested:
        try:
            audio_data, duration_ms = svc.tts_service.synthesize(
                response_text,
                detected_lang,
                emotion_label=validated_emotion.label,
                intensity=validated_emotion.intensity
            )
            audio_b64 = base64.b64encode(audio_data).decode("utf-8")
            audio_response = {
                "encoding": "base64",
                "data": audio_b64,
                "sample_rate": 22050,
                "mime_type": "audio/wav",
                "duration_ms": duration_ms
            }
        except Exception as e:
            logger.error(f"TTS synthesis failed: {str(e)}")
    
    timing["total_ms"] = int((time.time() - start_total) * 1000)
    
    # 🔹 NEW: Record token usage
    if token_usage is not None:
        from app import main as app_main
        if app_main.usage_api_handler and user_id and session_id:
            try:
                await app_main.usage_api_handler.record_usage(
                    user_id=user_id,
                    session_id=session_id,
                    endpoint="/interact",
                    token_usage=token_usage,
                    cache_hit=False
                )
                logger.debug(f"Recorded usage for {user_id}: {token_usage.total_tokens} tokens")
            except Exception as e:
                logger.error(f"Failed to record usage: {e}")
                # Don't fail the request, just log it
    
    # Build final response
    from datetime import datetime
    response = {
        "patient_response": {
            "text": response_text,
            "audio": audio_response,
            "emotion": {
                "label": validated_emotion.label,
                "intensity": validated_emotion.intensity
            }
        },
        "care_routing": {
            "recommended_pathway": final_care_routing.recommended_pathway.value,
            "urgency_level": final_care_routing.urgency_level.value
        },
        "clinical_summary": {
            "available": clinical_summary_obj.available,
            "summary_text": clinical_summary_obj.summary_text,
            "generated_at": clinical_summary_obj.generated_at.isoformat() if clinical_summary_obj.generated_at else None
        },
        # 🔹 NEW: Add token usage to response
        "token_usage": token_usage.to_dict() if token_usage else None,
        "timing": timing,
        "metadata": {
            "language_detected": detected_lang,
            "audio_mode": audio_mode,
            "translation_applied": translation_applied,
            "stt_confidence": round(confidence_score, 2),
            "safety_protocol": "ROSE_v1.0",
            "model": settings.GEMINI_MODEL,
            "architecture": "multimodal-v2-cached-streaming",
            "image_processed": bool(image_metadata),
            "image_metadata": {
                "format": image_metadata.get('original_format') if image_metadata else None,
                "dimensions": image_metadata.get('dimensions') if image_metadata else None,
                "consent_acknowledged": request.image_consent_acknowledged if image_metadata else None
            } if image_metadata else None,
            "image_analysis_included": bool(llm_response.get('image_analysis')) if image_metadata else False
        },
        "timestamp": datetime.utcnow().isoformat()
    }
    
    return response


@router.post(
    "/interact",
    response_model=TriageResponse,
    responses={
        200: {"description": "Successful triage interaction"},
        400: {"model": ErrorResponse, "description": "Invalid input"},
        413: {"model": ErrorResponse, "description": "Audio too large"},
        429: {"model": ErrorResponse, "description": "Quota exceeded"},
        500: {"model": ErrorResponse, "description": "Clinical safety protocol"}
    },
    summary="Primary triage interaction endpoint",
    description="""
    Processes patient input (text/audio/image) and returns structured response.
    Supports context caching and streaming for real-time responses.
    """
)
async def interact(
    request: TriageRequest,
    current_user: User = Depends(get_current_user),
    session_id: str = Header(None, alias="Session-Id"),
    settings = Depends(get_settings)
):
    """Main triage interaction endpoint.
    
    Required Headers:
        Authorization: Bearer <JWT_TOKEN>
    
    Optional Headers:
        Session-Id: Session identifier for usage tracking
    """
    try:
        # Generate session_id if not provided
        if not session_id:
            session_id = str(uuid.uuid4())
        
        svc = await get_service_container()
        result = await process_triage_request(
            request, settings, svc, stream_mode=False,
            user_id=current_user.id, session_id=session_id
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unhandled error in triage pipeline: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Clinical safety protocol activated. Session preserved for review."
        )


@router.post(
    "/interact/stream",
    responses={
        200: {"description": "Streaming triage interaction"},
        400: {"model": ErrorResponse, "description": "Invalid input"},
        429: {"model": ErrorResponse, "description": "Quota exceeded"},
    },
    summary="Streaming triage interaction endpoint",
    description="""
    Stream patient response tokens in real-time using Server-Sent Events (SSE).
    Provides immediate feedback while processing.
    """
)
async def interact_stream(
    request: TriageRequest,
    current_user: User = Depends(get_current_user),
    session_id: str = Header(None, alias="Session-Id"),
    settings = Depends(get_settings)
):
    """Streaming triage interaction endpoint.
    
    Required Headers:
        Authorization: Bearer <JWT_TOKEN>
    
    Optional Headers:
        Session-Id: Session identifier for usage tracking
    """
    try:
        # Generate session_id if not provided
        if not session_id:
            session_id = str(uuid.uuid4())
        
        svc = await get_service_container()
        result = await process_triage_request(
            request, settings, svc, stream_mode=True,
            user_id=current_user.id, session_id=session_id
        )
        
        return StreamingResponse(
            result["stream"],
            media_type="text/event-stream",
            headers={
                "X-Clinical-Safety-Protocol": "ROSE_v1.0",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )
    except HTTPException as he:
        # Return error as SSE event
        error_data = json.dumps({
            "type": "error",
            "error": he.detail,
            "status_code": he.status_code
        })
        async def error_stream():
            yield f"data: {error_data}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")
    except Exception as e:
        logger.exception(f"Unhandled error in streaming triage: {str(e)}")
        error_data = json.dumps({
            "type": "error",
            "error": "Clinical safety protocol activated",
            "status_code": 500
        })
        async def error_stream():
            yield f"data: {error_data}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")


@router.get(
    "/cache/stats",
    summary="Get context cache statistics",
    description="Returns statistics about the Gemini context cache usage."
)
async def get_cache_statistics():
    """Get cache statistics."""
    try:
        svc = await get_service_container()
        stats = await svc.gemini_service.get_cache_stats()
        if stats:
            return {"status": "success", "cache_stats": stats}
        return {"status": "disabled", "message": "Caching not enabled"}
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve cache statistics")