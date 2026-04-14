# app/services/speech_to_text.py
import base64
import io
import logging
import tempfile
import subprocess
from typing import Tuple
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

class SpeechToTextService:
    """Local Whisper STT - no Google Cloud required, runs on CPU/GPU"""
    
    # Model sizes: "tiny", "base", "small", "medium", "large-v3"
    # tiny=39MB (fast, less accurate), base=74MB, small=244MB (recommended for HF Spaces)
    MODEL_SIZE = "small"
    MAX_AUDIO_SIZE_BYTES = 5_000_000  # 5MB
    MAX_DURATION_SECONDS = 60
    
    def __init__(self):
        logger.info(f"Initializing Whisper model: {self.MODEL_SIZE}")
        
        # Auto-detect CPU/CUDA
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        
        # Download model on first run (cached in ~/.cache/huggingface)
        self.model = WhisperModel(
            self.MODEL_SIZE,
            device=device,
            compute_type=compute_type,
            download_root="/tmp/whisper_cache"  # HF Spaces friendly
        )
        
        logger.info(f"Whisper loaded on {device} ({compute_type})")
    
    def transcribe(self, audio_b64: str, mime_type: str = "audio/wav") -> Tuple[str, str, float]:
        """
        Transcribe audio using local Whisper.
        Returns: (transcript, language_code, confidence)
        """
        if not audio_b64:
            raise ValueError("Audio data empty")
        
        # Decode and validate
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception:
            raise ValueError("Invalid base64 audio")
        
        if len(audio_bytes) > self.MAX_AUDIO_SIZE_BYTES:
            raise ValueError(f"Audio too large: {len(audio_bytes)/1e6:.1f}MB")
        
        # Convert to WAV 16kHz mono (Whisper requirement)
        wav_bytes = self._normalize_audio(audio_bytes, mime_type)
        
        # Validate duration
        duration = len(wav_bytes) / (16000 * 2)  # 16kHz 16-bit
        if duration > self.MAX_DURATION_SECONDS:
            raise ValueError(f"Audio too long: {duration:.1f}s > {self.MAX_DURATION_SECONDS}s")
        
        # Transcribe with language detection
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                # Write proper WAV header + PCM data
                self._write_wav(tmp, wav_bytes, 16000)
                tmp_path = tmp.name
            
            segments, info = self.model.transcribe(
                tmp_path,
                beam_size=5,
                best_of=5,
                condition_on_previous_text=True,
                language=None  # Auto-detect language
            )
            
            # Collect transcription
            transcript = " ".join([seg.text for seg in segments]).strip()
            detected_lang = info.language  # e.g., "en", "es"
            confidence = 1.0 - (info.avg_logprob / -10.0)  # Normalize roughly
            
            # Cleanup temp file
            import os
            os.unlink(tmp_path)
            
            # Clinical safety validation
            transcript = self._validate_transcript(transcript)
            
            logger.info(f"Transcribed [{detected_lang}]: {len(transcript)} chars, confidence={confidence:.2f}")
            return transcript, detected_lang, min(confidence, 1.0)
            
        except Exception as e:
            logger.error(f"Whisper transcription failed: {str(e)}")
            raise RuntimeError(f"STT failed: {str(e)}")
    
    def _normalize_audio(self, audio_bytes: bytes, mime_type: str) -> bytes:
        """Convert any audio to 16kHz mono 16-bit PCM using ffmpeg"""
        mime_type = mime_type.lower()
        
        with tempfile.NamedTemporaryFile(suffix=".input", delete=False) as inp, \
             tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out:
            
            inp.write(audio_bytes)
            inp.flush()
            
            # ffmpeg conversion
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", inp.name,
                "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
                "-f", "wav", out.name
            ]
            
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=15)
                with open(out.name, "rb") as f:
                    data = f.read()
                    # Skip 44-byte WAV header
                    return data[44:] if len(data) > 44 else data
            except subprocess.CalledProcessError as e:
                raise ValueError(f"Audio conversion failed: {e.stderr.decode()[:100]}")
            finally:
                import os
                os.unlink(inp.name)
                os.unlink(out.name)
    
    def _write_wav(self, file_obj, pcm_data: bytes, sample_rate: int):
        """Write WAV header + PCM data"""
        import struct
        channels = 1
        bits_per_sample = 16
        byte_rate = sample_rate * channels * bits_per_sample // 8
        
        # WAV header
        file_obj.write(b'RIFF')
        file_obj.write(struct.pack('<I', 36 + len(pcm_data)))
        file_obj.write(b'WAVE')
        file_obj.write(b'fmt ')
        file_obj.write(struct.pack('<I', 16))
        file_obj.write(struct.pack('<HH', 1, channels))  # PCM, mono
        file_obj.write(struct.pack('<I', sample_rate))
        file_obj.write(struct.pack('<I', byte_rate))
        file_obj.write(struct.pack('<HH', channels * bits_per_sample // 8, bits_per_sample))
        file_obj.write(b'data')
        file_obj.write(struct.pack('<I', len(pcm_data)))
        file_obj.write(pcm_data)
    
    def _validate_transcript(self, text: str) -> str:
        """Block prompt injection via audio"""
        blocked = ['ignore previous', 'system prompt', 'you are now', 'jailbreak', 'base64:']
        lower = text.lower()
        if any(b in lower for b in blocked):
            logger.warning("Blocked potential injection in audio transcript")
            return "[ unclear - please describe symptoms again ]"
        return text