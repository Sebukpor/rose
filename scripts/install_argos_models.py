#!/usr/bin/env python3
"""
Pre-install Argos Translate models to avoid runtime delays.
"""
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    try:
        import argostranslate.package
        import argostranslate.translate
        
        logger.info("Updating Argos package index...")
        try:
            argostranslate.package.update_package_index()
        except Exception as e:
            logger.warning(f"Failed to update package index: {e}")
            logger.info("Continuing with offline mode...")
            return 0
        
        available_packages = argostranslate.package.get_available_packages()
        target_codes = ['en', 'es', 'fr', 'de', 'it', 'pt', 'sw', 'zh', 'hi'] 
        installed = 0

        for from_code in target_codes:
            for to_code in target_codes:
                if from_code == to_code:
                    continue
                    
                pkg = next(
                    (p for p in available_packages 
                     if p.from_code == from_code and p.to_code == to_code),
                    None
                )
                if pkg:
                    try:
                        download_path = pkg.download()
                        argostranslate.package.install_from_path(download_path)
                        installed += 1
                        logger.info(f'✓ Installed {from_code} → {to_code}')
                    except Exception as e:
                        logger.warning(f'✗ Failed {from_code} → {to_code}: {str(e)[:80]}')
        
        logger.info(f'Total models installed: {installed}')
        installed_langs = argostranslate.translate.get_installed_languages()
        logger.info(f'Available languages: {", ".join([lang.code for lang in installed_langs])}')
        return 0
        
    except ImportError as e:
        logger.warning(f"Argos translate not available: {e}")
        logger.info("Continuing without pre-installed models...")
        return 0
    except Exception as e:
        logger.warning(f"Argos installation failed: {e}")
        logger.info("Models will download at runtime if needed")
        return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)