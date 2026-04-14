#!/usr/bin/env python3
"""Verify multimodal dependencies are correctly installed."""

def check():
    print("🔍 Verifying ROSE Multimodal Dependencies...\n")
    
    # Core image processing
    try:
        from PIL import Image, ExifTags
        print(f"✅ Pillow {Image.__version__} - Image processing ready")
    except ImportError as e:
        print(f"❌ Pillow missing: {e}")
        return False
    
    # HEIC support
    try:
        import pillow_heif
        print(f"✅ pillow-heif - HEIC/HEIF support enabled")
    except ImportError:
        print("⚠️  pillow-heif not installed (iPhone HEIC support disabled)")
    
    # Security
    try:
        import cryptography
        print(f"✅ cryptography - Audit encryption available")
    except ImportError:
        print("⚠️  cryptography not installed (audit logs will be plaintext)")
    
    # Gemini
    try:
        import google.generativeai as genai
        print(f"✅ google-generativeai - Multimodal LLM ready")
    except ImportError:
        print("❌ google-generativeai missing")
        return False
    
    print("\n✅ All critical multimodal dependencies verified!")
    return True

if __name__ == "__main__":
    import sys
    sys.exit(0 if check() else 1)