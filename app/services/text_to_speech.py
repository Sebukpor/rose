# app/services/text_to_speech.py
import io
import logging
import tempfile
import subprocess
import numpy as np
from pathlib import Path
from typing import Tuple
import struct

logger = logging.getLogger(__name__)


class TextToSpeechService:
    """
    Local Piper TTS - high quality, offline, multilingual
    """

    # 🔹 Language → Voice mapping (includes Hindi)
    VOICES = {
        "en": "en_US-amy-medium",
        "es": "es_AR-daniela-high",
        "fr": "fr_FR-siwis-medium",
        "de": "de_DE-ramona-low",
        "it": "it_IT-paola-medium",
        "pt": "es_AR-daniela-high",
        "hi": "hi_IN-priyamvada-medium",  
        "sw": "sw_CD-lanfrica-medium",
        "zh": "zh_CN-huayan-medium",
        "default": "en_US-amy-medium"
    }



    # 🔹 HuggingFace relative paths (official Piper v1.0.0)
    VOICE_PATHS = {
        "en_US-amy-medium": "en/en_US/amy/medium/en_US-amy-medium.onnx",
        "es_AR-daniela-high": "es/es_AR/daniela/high/es_AR-daniela-high.onnx",
        "fr_FR-siwis-medium": "fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx",
        "de_DE-ramona-low": "de/de_DE/ramona/low/de_DE-ramona-low.onnx",
        "it_IT-paola-medium": "it/it_IT/paola/medium/it_IT-paola-medium.onnx",
        "pt_AR-daniela-high": "es/es_AR/daniela/high/es_AR-daniela-high.onnx",
        "sw_CD-lanfrica-medium": "sw/sw_CD/lanfrica/medium/sw_CD-lanfrica-medium.onnx",
        "zh_CN-huayan-medium": "zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx",
        "hi_IN-priyamvada-medium": "hi/hi_IN/priyamvada/medium/hi_IN-priyamvada-medium.onnx",  # 🇮🇳 Hindi
    }

    SAMPLE_RATE = 22050
    PIPER_AVAILABLE = False

    def __init__(self):
        self.voice_dir = Path("/tmp/piper_voices")
        self.voice_dir.mkdir(exist_ok=True)
        self._ensure_piper_installed()
        self._download_voices()
        logger.info("Piper TTS initialized successfully")

    def _ensure_piper_installed(self):
        try:
            result = subprocess.run(
                ["piper", "--version"],
                capture_output=True,
                check=True,
                timeout=5
            )
            self.PIPER_AVAILABLE = True
            logger.info(f"Piper binary detected: {result.stdout.decode().strip()}")
        except Exception as e:
            logger.warning(f"Piper binary not found: {e}")
            self.PIPER_AVAILABLE = False

    def _download_voices(self):
        import urllib.request

        base_url = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"

        for voice, relative_path in self.VOICE_PATHS.items():
            onnx_file = self.voice_dir / f"{voice}.onnx"
            json_file = self.voice_dir / f"{voice}.onnx.json"

            if onnx_file.exists() and json_file.exists():
                continue

            logger.info(f"Downloading Piper voice: {voice}")

            for url, dest in [
                (f"{base_url}/{relative_path}", onnx_file),
                (f"{base_url}/{relative_path}.json", json_file),
            ]:
                if dest.exists():
                    continue

                try:
                    req = urllib.request.Request(
                        url,
                        headers={"User-Agent": "Piper-TTS/1.0"}
                    )
                    with urllib.request.urlopen(req, timeout=60) as response:
                        dest.write_bytes(response.read())

                    logger.info(f"Downloaded {dest.name} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
                except Exception as e:
                    logger.error(f"Failed downloading {dest.name}: {e}")
                    if dest.exists():
                        dest.unlink()

    def synthesize(
        self,
        text: str,
        language_code: str,
        emotion_label: str = "calm",
        intensity: float = 0.5
    ) -> Tuple[bytes, int]:

        if not text.strip():
            raise ValueError("Text input is empty")

        lang = language_code.split("-")[0].lower()
        voice_name = self.VOICES.get(lang, self.VOICES["default"])
        voice_path = self.voice_dir / f"{voice_name}.onnx"

        if not voice_path.exists():
            logger.warning(f"Voice {voice_name} missing. Falling back to default.")
            voice_name = self.VOICES["default"]
            voice_path = self.voice_dir / f"{voice_name}.onnx"

        if not self.PIPER_AVAILABLE or not voice_path.exists():
            return self._fallback_beep()

        # 🔹 FIXED: Pass language code to emotional prosody processor
        emotional_text = self._apply_emotional_prosody(text, emotion_label, intensity, lang)

        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                output_path = tmp.name

            length_scale = max(0.85, 1.0 - intensity * 0.15)

            cmd = [
                "piper",
                "-m", str(voice_path),
                "-f", output_path,
                "--length_scale", str(length_scale),
                "--sentence_silence", "0.2"
            ]

            proc = subprocess.run(
                cmd,
                input=emotional_text.encode("utf-8"),
                capture_output=True,
                timeout=30
            )

            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode())

            wav_data = Path(output_path).read_bytes()

            pcm_size = max(0, len(wav_data) - 44)
            duration_ms = int((pcm_size / (self.SAMPLE_RATE * 2)) * 1000)

            Path(output_path).unlink(missing_ok=True)
            return wav_data, duration_ms

        except Exception as e:
            logger.error(f"TTS failed: {e}")
            return self._fallback_beep()

    def _apply_emotional_prosody(
        self, 
        text: str, 
        emotion: str, 
        intensity: float,
        language: str = "en"  # 🔹 ADDED: Language parameter with default fallback
    ) -> str:
        """
        Apply emotional prosody modifications based on emotion label and target language.
        Language-specific suffixes ensure appropriate emotional expression per culture.
        """
        
        # 🔹 FIXED: Language-specific emotional suffixes to avoid mixing languages
        suffixes = {
            "en": {
                "reassuring": " I'm here to help.",
                "concerned": " Please tell me more."
            },
            "es": {
                "reassuring": " Estoy aquí para ayudar.",
                "concerned": " Por favor, cuénteme más."
            },
            "fr": {
                "reassuring": " Je suis là pour vous aider.",
                "concerned": " Veuillez m'en dire plus."
            },
            "de": {
                "reassuring": " Ich bin hier, um zu helfen.",
                "concerned": " Bitte erzählen Sie mir mehr."
            },
            "it": {
                "reassuring": " Sono qui per aiutarla.",
                "concerned": " Mi dica di più, per favore."
            },
            "pt": {
                "reassuring": " Estou aqui para ajudar.",
                "concerned": " Por favor, me conte mais."
            },
            "hi": {  # 🇮🇳 Hindi added
                "reassuring": " मैं आपकी मदद के लिए यहाँ हूँ।",
                "concerned": " कृपया और बताइए।"
            },
            "sw": { # 🇰🇪🇹🇿🇨🇩 Swahili added 
                "reassuring": " Niko hapa kukusaidia.", 
                "concerned": " Tafadhali niambie zaidi." 
            },
            "zh": { # 🇨🇳 Chinese (Mandarin) added 
                "reassuring": " 我在这里帮助你。", 
                "concerned": " 请告诉我更多。" 
            },
        }
        
        # Get language-specific suffixes, fallback to English if unknown
        lang_suffixes = suffixes.get(language, suffixes["en"])
        
        # Base modifiers (language-agnostic text transformations)
        modifiers = {
            "calm": text,
            "empathetic": text.replace(".", "...").replace("!", "."),
            "reassuring": f"{text}{lang_suffixes.get('reassuring', '')}",
            "attentive": text,
            "concerned": f"{text}{lang_suffixes.get('concerned', '')}",
            "neutral": text
        }
        
        return modifiers.get(emotion, text)

    def _fallback_beep(self) -> Tuple[bytes, int]:
        duration = 0.5
        t = np.linspace(0, duration, int(self.SAMPLE_RATE * duration), False)
        tone = np.sin(2 * np.pi * 440 * t) * 0.3
        pcm = (tone * 32767).astype(np.int16).tobytes()
        return self._wav_header(len(pcm)) + pcm, int(duration * 1000)

    def _wav_header(self, data_len: int) -> bytes:
        byte_rate = self.SAMPLE_RATE * 2
        return struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_len,
            b"WAVE",
            b"fmt ",
            16,
            1,
            1,
            self.SAMPLE_RATE,
            byte_rate,
            2,
            16,
            b"data",
            data_len
        )