from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo
from typing import Optional, List
from enum import Enum
import base64

class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"

class Message(BaseModel):
    role: MessageRole
    content: str = Field(..., min_length=1, max_length=2000)
    language: str = Field("en", description="BCP-47 language code of original content")
    attached_images: Optional[List[str]] = Field(default=None)

class InputType(str, Enum):
    text = "text"
    audio = "audio"
    image = "image"
    multimodal = "multimodal"

class ResponseMode(str, Enum):
    text = "text"
    audio = "audio"
    both = "both"

class ImageInput(BaseModel):
    """Image input - all fields optional, validation only when data present"""
    model_config = {
        "extra": "ignore",  # Ignore extra fields
        "validate_default": False,
    }
    
    data: Optional[str] = Field(
        default=None,
        description="Base64-encoded image data"
    )
    mime_type: Optional[str] = Field(
        default=None,
        description="Image MIME type"
    )
    description: Optional[str] = Field(
        default=None, 
        max_length=500,
        description="Optional patient description"
    )
    
    @field_validator('data', mode='before')
    @classmethod
    def validate_data(cls, v):
        # If None or empty, return None (no validation needed)
        if v is None or v == "" or v == "null" or v == "string":
            return None
        
        # If it's already bytes, convert to string
        if isinstance(v, bytes):
            v = v.decode('utf-8')
        
        # Must be string at this point
        if not isinstance(v, str):
            raise ValueError("Image data must be a base64 string")
        
        # Check for placeholder/test values that frontend might send
        if v in ["string", "test", "null", "undefined", "data"]:
            return None
            
        # Check length (rough estimate: 7MB = ~9.3MB base64)
        if len(v) > 10_000_000:
            raise ValueError("Image exceeds maximum size limit (~7MB)")
        
        # Try to decode to verify it's valid base64
        try:
            # Remove data URL prefix if present
            if ',' in v:
                v = v.split(',')[1]
            
            decoded = base64.b64decode(v, validate=True)
            if len(decoded) > 7_000_000:
                raise ValueError("Image exceeds 7MB size limit")
            if len(decoded) < 100:
                raise ValueError("Image data too small")
        except Exception as e:
            raise ValueError(f"Invalid base64 encoding: {str(e)}")
        
        return v
    
    @field_validator('mime_type', mode='before')
    @classmethod
    def validate_mime(cls, v):
        # If None or empty, return None
        if v is None or v == "" or v == "null" or v == "string":
            return None
        
        allowed = ["image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"]
        
        # Handle common variations
        v = str(v).lower().strip()
        if v == "jpg":
            v = "image/jpeg"
        elif v == "png":
            v = "image/png"
        elif v == "webp":
            v = "image/webp"
        
        if v not in allowed:
            raise ValueError(f"Unsupported image type. Allowed: {allowed}")
        
        return v

class TriageRequest(BaseModel):
    model_config = {
        "extra": "ignore",
        "validate_default": False,
    }
    
    conversation_history: List[Message] = Field(default_factory=list)
    current_input_type: InputType
    current_input_text: Optional[str] = Field(default=None)
    current_input_audio: Optional[str] = Field(default=None)
    current_input_image: Optional[ImageInput] = Field(default=None)
    current_input_language: Optional[str] = Field(
        default="en",
        description="BCP-47 language code for the current input (e.g., 'en', 'es', 'fr', 'zh', 'sw')"
    )
    image_consent_acknowledged: bool = Field(default=False)
    response_mode: ResponseMode = Field(default=ResponseMode.text)
    
    
    @model_validator(mode='before')
    @classmethod
    def check_inputs(cls, data: dict):
        input_type = data.get('current_input_type')
        
        # Get image data safely
        image_data = data.get('current_input_image')
        has_image = False
        
        if isinstance(image_data, dict):
            img_data = image_data.get('data')
            has_image = img_data is not None and img_data not in [None, "", "null", "string", "undefined"]
        elif isinstance(image_data, ImageInput):
            has_image = image_data.data is not None
        
        has_text = bool(data.get('current_input_text'))
        has_audio = bool(data.get('current_input_audio'))
        
        # Validate based on type
        if input_type == 'text' and not has_text:
            raise ValueError("Text input required")
        elif input_type == 'audio' and not has_audio:
            raise ValueError("Audio input required")
        elif input_type == 'image' and not has_image:
            raise ValueError("Image input required")
        elif input_type == 'multimodal' and not (has_text and has_image):
            raise ValueError("Both text and image required for multimodal")
        
        # Only check consent if image is actually present
        if has_image and not data.get('image_consent_acknowledged'):
            raise ValueError("Consent required for image processing")
        
        return data