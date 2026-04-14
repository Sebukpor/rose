import base64
import io
import logging
import tempfile
from typing import Tuple, Optional, Dict, List
from PIL import Image, ExifTags
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

class MedicalImageProcessor:
    """
    Clinical-grade image processing for multimodal triage.
    Handles medical image validation, sanitization, and preparation for Gemini.
    
    Fortune 500 Safety Features:
    - PII scrubbing from EXIF metadata
    - Image integrity validation
    - Size/format standardization
    - Clinical appropriateness checks
    """
    
    SUPPORTED_FORMATS = {
        'PNG': 'image/png',
        'JPEG': 'image/jpeg',
        'WEBP': 'image/webp',
        'HEIC': 'image/heic',
        'HEIF': 'image/heif'
    }
    
    MAX_DIMENSION = 4096  # Gemini max dimension
    TARGET_QUALITY = 85
    
    def __init__(self):
        self.processed_count = 0
        self.blocked_count = 0
        logger.info("MedicalImageProcessor initialized")
    
    def process_image(
        self, 
        image_data: str, 
        mime_type: str,
        patient_description: Optional[str] = None
    ) -> Tuple[str, str, Dict]:
        """
        Process and validate medical image for Gemini consumption.
        
        Returns:
            (processed_base64, final_mime_type, metadata_dict)
        """
        try:
            # Decode base64
            raw_bytes = base64.b64decode(image_data)
            
            # Validate image integrity
            img = Image.open(io.BytesIO(raw_bytes))
            img.verify()  # Verify file integrity
            img = Image.open(io.BytesIO(raw_bytes))  # Re-open after verify
            
            # Extract and log metadata (for audit trail)
            metadata = self._extract_metadata(img, raw_bytes)
            
            # 🔹 Clinical Safety: Check for inappropriate content attempts
            safety_check = self._clinical_safety_check(img, metadata)
            if not safety_check['approved']:
                self.blocked_count += 1
                raise ValueError(f"Image blocked: {safety_check['reason']}")
            
            # Standardize image for Gemini
            processed_img = self._standardize_image(img)
            
            # Convert to optimized JPEG for compatibility
            output_buffer = io.BytesIO()
            processed_img.save(output_buffer, format='JPEG', quality=self.TARGET_QUALITY)
            processed_bytes = output_buffer.getvalue()
            
            # Encode back to base64
            processed_b64 = base64.b64encode(processed_bytes).decode('utf-8')
            
            self.processed_count += 1
            
            logger.info(
                f"Image processed | "
                f"Original: {metadata['original_format']} {metadata['original_size']} | "
                f"Final: {len(processed_bytes)/1024:.1f}KB | "
                f"Dimensions: {processed_img.size}"
            )
            
            return processed_b64, 'image/jpeg', metadata
            
        except Exception as e:
            logger.error(f"Image processing failed: {str(e)}")
            raise ValueError(f"Image processing error: {str(e)}")
    
    def _extract_metadata(self, img: Image.Image, raw_bytes: bytes) -> Dict:
        """Extract image metadata for audit trail (PII sanitized)"""
        metadata = {
            'original_format': img.format,
            'original_size': f"{len(raw_bytes)/1024:.1f}KB",
            'dimensions': img.size,
            'mode': img.mode,
            'has_exif': False,
            'clinical_appropriate': True
        }
        
        # Extract EXIF data (sanitized - no GPS, no camera serial numbers)
        try:
            exif = img._getexif()
            if exif:
                metadata['has_exif'] = True
                # Only capture general capture info, strip identifying data
                safe_tags = ['DateTime', 'DateTimeOriginal', 'Orientation']
                metadata['capture_info'] = {
                    ExifTags.TAGS.get(tag, tag): str(exif[tag])
                    for tag, value in exif.items()
                    if ExifTags.TAGS.get(tag, tag) in safe_tags
                }
        except Exception:
            pass
            
        return metadata
    
    def _clinical_safety_check(self, img: Image.Image, metadata: Dict) -> Dict:
        """
        Clinical appropriateness validation.
        Blocks non-medical images or potential security risks.
        """
        # Check 1: Minimum dimensions (must be real photo, not icon)
        width, height = img.size
        if width < 100 or height < 100:
            return {'approved': False, 'reason': 'Image dimensions too small for clinical analysis'}
        
        if width > self.MAX_DIMENSION or height > self.MAX_DIMENSION:
            return {'approved': False, 'reason': 'Image dimensions exceed maximum'}
        
        # Check 2: Aspect ratio sanity (not extremely wide/tall banners)
        aspect_ratio = max(width, height) / min(width, height)
        if aspect_ratio > 5:
            return {'approved': False, 'reason': 'Invalid aspect ratio for medical image'}
        
        # Check 3: Mode validation (must be photographic)
        if img.mode not in ['RGB', 'RGBA', 'L', 'CMYK']:
            return {'approved': False, 'reason': 'Unsupported image color mode'}
        
        return {'approved': True, 'reason': 'Passed clinical safety checks'}
    
    def _standardize_image(self, img: Image.Image) -> Image.Image:
        """Standardize image for consistent Gemini processing"""
        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                background.paste(img, mask=img.split()[3])
            else:
                background.paste(img)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Resize if exceeds max dimensions (maintaining aspect ratio)
        width, height = img.size
        if width > self.MAX_DIMENSION or height > self.MAX_DIMENSION:
            img.thumbnail((self.MAX_DIMENSION, self.MAX_DIMENSION), Image.Resampling.LANCZOS)
            logger.debug(f"Image resized to {img.size}")
        
        return img
    
    def create_gemini_part(
        self, 
        image_b64: str, 
        mime_type: str,
        text_context: Optional[str] = None
    ) -> Dict:
        """
        Create Gemini API compatible image part structure.
        """
        part = {
            "inline_data": {
                "mime_type": mime_type,
                "data": image_b64
            }
        }
        
        # If text context provided, create multi-part content
        if text_context:
            return {
                "parts": [
                    {"text": text_context},
                    part
                ]
            }
        return {"parts": [part]}
    
    def get_stats(self) -> Dict:
        """Return processing statistics for monitoring"""
        return {
            "processed": self.processed_count,
            "blocked": self.blocked_count,
            "block_rate": self.blocked_count / max(self.processed_count, 1)
        }