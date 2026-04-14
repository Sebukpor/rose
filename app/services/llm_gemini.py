import json
import logging
import time
import asyncio
from typing import Dict, List, Tuple, Optional, Any, AsyncGenerator
from google import genai
from google.genai import types
from pydantic import ValidationError
from app.core.config import get_settings
from app.models.response import CareRouting, EmotionMetadata
from app.services.gemini_cache_manager import get_cache_manager, GeminiCacheManager
from app.services.token_counter import TokenCounter, TokenUsage
logger = logging.getLogger(__name__)
settings = get_settings()
class GeminiService:
    """
    Handles all Gemini interactions with clinical safety guards, context caching, and streaming.
   
    Features:
    - Explicit context caching for system prompts
    - Streaming responses for real-time patient interaction
    - Multimodal support (text, image, audio)
    """
   
    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.model_name = settings.GEMINI_MODEL
        self.temperature = settings.GEMINI_TEMPERATURE
        self.cache_manager: Optional[GeminiCacheManager] = None
        logger.info(f"Gemini service initialized: {self.model_name} (Caching + Streaming enabled)")
   
    async def initialize(self):
        """Initialize cache manager"""
        self.cache_manager = await get_cache_manager()
        self.cache_manager.set_client(self.client)
   
    async def generate_triage_response(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, Any]],
        current_multimodal_input: Optional[Dict] = None,
        use_streaming: bool = False
    ) -> Tuple[Dict, float, Optional[TokenUsage]]:
        """
        Generate patient response + metadata with context caching and optional streaming.
       
        Args:
            system_prompt: The ROSE system prompt
            conversation_history: Previous conversation turns
            current_multimodal_input: Current input (text + optional image)
            use_streaming: Whether to use streaming (returns first chunk info, full response collected)
       
        Returns:
            Tuple of (parsed_response_dict, duration_ms, token_usage)
        """
        start = time.time()
        token_usage = None
       
        # Get or create cached context
        cache_name = None
        if self.cache_manager and settings.GEMINI_CACHE_ENABLED:
            cache_name, is_new = await self.cache_manager.get_or_create_cache(
                system_prompt=system_prompt,
                model_name=self.model_name
            )
       
        # Build contents
        contents = self._build_contents(conversation_history, current_multimodal_input)
       
        # Prepend system prompt enforcement if not using cache
        if not cache_name:
            contents = [
                types.Content(role="user", parts=[types.Part.from_text(text=system_prompt)]),
                types.Content(role="model", parts=[types.Part.from_text(text="Understood. I will follow all instructions precisely.")])
            ] + contents
       
        # Configure generation
        config = types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=1024,
            response_mime_type="application/json",
            safety_settings=[
                types.SafetySetting(
                    category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    threshold="BLOCK_NONE"
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_HATE_SPEECH",
                    threshold="BLOCK_NONE"
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_HARASSMENT",
                    threshold="BLOCK_NONE"
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_DANGEROUS_CONTENT",
                    threshold="BLOCK_MEDIUM_AND_ABOVE"
                )
            ]
        )
       
        # Use cached content if available
        if cache_name:
            config.cached_content = cache_name
       
        try:
            if use_streaming and settings.STREAMING_ENABLED:
                # Streaming mode - collect full response
                response_text = ""
                response_obj = None
                async for chunk in await self.client.aio.models.generate_content_stream(
                    model=self.model_name,
                    contents=contents,
                    config=config
                ):
                    if chunk.text:
                        response_text += chunk.text
                    response_obj = chunk  # Keep last chunk for token info
               
                parsed = self._parse_response(response_text)
                # Extract tokens from last chunk (which has usage metadata)
                if response_obj:
                    token_usage = TokenCounter.extract_from_response(response_obj)
            else:
                # Non-streaming mode
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=config
                )
                parsed = self._parse_response(response.text)
                # Extract tokens from response
                token_usage = TokenCounter.extract_from_response(response)
           
            duration = (time.time() - start) * 1000
            logger.info(
                f"Triage LLM call completed: {duration:.0f}ms (cached={cache_name is not None}) "
                f"tokens={token_usage.total_tokens if token_usage else 'N/A'}"
            )
            return parsed, duration, token_usage
           
        except Exception as e:
            logger.error(f"LLM generation failed: {str(e)}")
            return self._fallback_response(), (time.time() - start) * 1000, None
   
    async def generate_triage_response_stream(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, Any]],
        current_multimodal_input: Optional[Dict] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream patient response tokens in real-time.
       
        Yields JSON chunks that can be parsed incrementally or collected.
        """
        # Get or create cached context
        cache_name = None
        if self.cache_manager and settings.GEMINI_CACHE_ENABLED:
            cache_name, _ = await self.cache_manager.get_or_create_cache(
                system_prompt=system_prompt,
                model_name=self.model_name
            )
       
        # Build contents
        contents = self._build_contents(conversation_history, current_multimodal_input)
       
        # Prepend system prompt enforcement if not using cache
        if not cache_name:
            contents = [
                types.Content(role="user", parts=[types.Part.from_text(text=system_prompt)]),
                types.Content(role="model", parts=[types.Part.from_text(text="Understood. I will follow all instructions precisely.")])
            ] + contents
       
        # Configure generation
        config = types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=1024,
            response_mime_type="application/json",
            safety_settings=[
                types.SafetySetting(
                    category="HARM_CATEGORY_DANGEROUS_CONTENT",
                    threshold="BLOCK_MEDIUM_AND_ABOVE"
                )
            ]
        )
       
        if cache_name:
            config.cached_content = cache_name
       
        try:
            async for chunk in await self.client.aio.models.generate_content_stream(
                model=self.model_name,
                contents=contents,
                config=config
            ):
                if chunk.text:
                    yield chunk.text
                   
        except Exception as e:
            logger.error(f"Streaming generation failed: {str(e)}")
            # Yield fallback response
            fallback = json.dumps(self._fallback_response())
            yield fallback
   
    def _build_contents(
        self,
        conversation_history: List[Dict[str, Any]],
        current_multimodal_input: Optional[Dict]
    ) -> List[types.Content]:
        """Build content list from history and current input"""
        contents = []
       
        # Add conversation history
        for msg in conversation_history:
            role = "user" if msg["role"] == "user" else "model"
            parts = []
           
            if "content" in msg and msg["content"]:
                parts.append(types.Part.from_text(text=msg["content"]))
           
            if "image_data" in msg and msg["image_data"]:
                parts.append(types.Part.from_bytes(
                    data=msg["image_data"],
                    mime_type=msg.get("image_mime", "image/jpeg")
                ))
           
            if parts:
                contents.append(types.Content(role=role, parts=parts))
       
        # Add current input
        if current_multimodal_input:
            parts = []
           
            if "text" in current_multimodal_input:
                parts.append(types.Part.from_text(text=current_multimodal_input["text"]))
           
            if "image" in current_multimodal_input:
                img_data = current_multimodal_input["image"]
                parts.append(types.Part.from_bytes(
                    data=img_data["data"],
                    mime_type=img_data["mime_type"]
                ))
           
            if parts:
                contents.append(types.Content(role="user", parts=parts))
       
        return contents
   
    def _parse_response(self, text: str) -> Dict:
        """Parse and validate JSON response with better error handling"""
        try:
            # Try to parse as-is first
            parsed = json.loads(text)
           
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            import re
           
            # Look for JSON in code blocks
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(1))
                    logger.info("Extracted JSON from markdown code block")
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse extracted JSON: {json_match.group(1)[:200]}")
                    return self._fallback_response()
            else:
                # Try to find any JSON-like structure
                json_match = re.search(r'(\{.*"patient_message".*"care_routing".*\})', text, re.DOTALL)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group(1))
                        logger.info("Extracted JSON from raw text")
                    except json.JSONDecodeError:
                        logger.error(f"Response is not valid JSON: {text[:500]}")
                        return self._fallback_response()
                else:
                    logger.error(f"No JSON found in response: {text[:500]}")
                    return self._fallback_response()
       
        # Validate required fields
        required = ["patient_message", "care_routing", "emotion", "generate_clinical_summary"]
        missing = [k for k in required if k not in parsed]
       
        if missing:
            logger.error(f"Missing required fields: {missing}. Response: {json.dumps(parsed)[:500]}")
            # Try to fill in defaults for missing fields
            if "patient_message" not in parsed:
                parsed["patient_message"] = "I want to make sure I understand your symptoms correctly. Could you describe them again?"
            if "care_routing" not in parsed:
                parsed["care_routing"] = {"recommended_pathway": "doctor", "urgency_level": "moderate"}
            if "emotion" not in parsed:
                parsed["emotion"] = {"label": "attentive", "intensity": 0.8}
            if "generate_clinical_summary" not in parsed:
                parsed["generate_clinical_summary"] = False
       
        # Validate image analysis if present
        if "image_analysis" in parsed:
            parsed["image_analysis"] = self._validate_image_analysis(parsed["image_analysis"])
       
        # Validate enums
        try:
            CareRouting(**parsed["care_routing"])
            EmotionMetadata(**parsed["emotion"])
        except ValidationError as e:
            logger.error(f"Validation error: {e}")
            return self._fallback_response()
       
        return parsed
   
    def _fallback_response(self) -> Dict:
        """Safe fallback response when generation fails"""
        return {
            "patient_message": "I want to make sure I understand your symptoms correctly. Could you describe them again in your own words?",
            "care_routing": {"recommended_pathway": "doctor", "urgency_level": "moderate"},
            "emotion": {"label": "attentive", "intensity": 0.8},
            "generate_clinical_summary": False,
            "image_analysis": None
        }
   
    def _validate_image_analysis(self, analysis: Dict) -> Dict:
        """Sanitize image analysis to prevent diagnostic overreach"""
        if not isinstance(analysis, dict):
            return None
       
        # Block diagnostic language
        blocked_terms = ['diagnosis', 'diagnosed', 'condition is', 'you have', 'disease']
        description = analysis.get('description', '').lower()
       
        if any(term in description for term in blocked_terms):
            logger.warning("Blocked diagnostic language in image analysis")
            analysis['description'] = '[Visual observation noted]'
            analysis['clinical_findings'] = None
       
        # Cap confidence
        if 'confidence' in analysis and analysis['confidence'] > 0.8:
            analysis['confidence'] = 0.75
       
        return analysis
   
    async def generate_clinical_summary(
        self,
        clinical_prompt: str,
        conversation_history: List[Dict[str, Any]],
        include_image_observations: bool = False
    ) -> Tuple[Optional[str], Optional[TokenUsage]]:
        """Generate provider-facing clinical summary with optional caching and token tracking"""
        try:
            # Build conversation history
            history_parts = []
            for msg in conversation_history:
                entry = f"[{msg['role'].upper()}]: {msg.get('content', '')}"
                if "image_data" in msg and msg["image_data"]:
                    entry += " [Patient provided image for visual assessment]"
                history_parts.append(entry)
           
            history_str = "\n".join(history_parts)
            prompt = clinical_prompt.replace("{conversation_history}", history_str)
           
            if include_image_observations:
                prompt += "\n\nNote: Patient provided visual documentation during triage."
           
            # Get cache for clinical prompt (different cache from triage)
            cache_name = None
            if self.cache_manager and settings.GEMINI_CACHE_ENABLED:
                cache_name, _ = await self.cache_manager.get_or_create_cache(
                    system_prompt=clinical_prompt,
                    model_name=self.model_name
                )
           
            config = types.GenerateContentConfig(
                safety_settings=[
                    types.SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT",
                        threshold="BLOCK_MEDIUM_AND_ABOVE"
                    )
                ]
            )
           
            if cache_name:
                config.cached_content = cache_name
           
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
                config=config
            )
           
            summary = response.text.strip()
            token_usage = TokenCounter.extract_from_response(response)
           
            # Safety validation
            if "INSUFFICIENT_DATA" in summary or len(summary) < 20:
                return None, token_usage
           
            blocked_terms = ["diagnosis", "prescribe", "treatment plan", "I think you have"]
            if any(term in summary.lower() for term in blocked_terms):
                logger.warning("Clinical summary blocked: contains prohibited language")
                return None, token_usage
           
            return summary, token_usage
           
        except Exception as e:
            logger.error(f"Clinical summary generation failed: {str(e)}")
            return None, None
   
    async def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """Get cache statistics if available"""
        if self.cache_manager:
            return await self.cache_manager.get_cache_stats()
        return None