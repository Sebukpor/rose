"""
Token Counter Service - Extracts and tracks token usage from Gemini API responses.
Integrates with usage limiting for freemium model support.
"""
import logging
from typing import Dict, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Represents token usage for a single API call"""
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0  # Gemini context cache tokens
    
    @property
    def total_tokens(self) -> int:
        """Total billable tokens (cached tokens are at reduced rate)"""
        # Per Gemini pricing: cached tokens count as 10% of normal rate
        cached_cost = int(self.cached_tokens * 0.10)
        return self.input_tokens + self.output_tokens + cached_cost
    
    @property
    def total_tokens_raw(self) -> int:
        """Total tokens including cached (for analytics)"""
        return self.input_tokens + self.output_tokens + self.cached_tokens
    
    def to_dict(self) -> Dict[str, int]:
        """Export as dictionary for storage"""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "total_tokens": self.total_tokens,
            "total_tokens_raw": self.total_tokens_raw
        }


class TokenCounter:
    """Extracts and counts tokens from Gemini API responses"""
    
    @staticmethod
    def extract_from_response(response: Any) -> TokenUsage:
        """
        Extract token usage from Gemini API response object.
        
        Handles both streaming and non-streaming responses.
        """
        try:
            input_tokens = 0
            output_tokens = 0
            cached_tokens = 0
            
            # Check for usage metadata in response
            if hasattr(response, 'usage_metadata'):
                metadata = response.usage_metadata
                input_tokens = getattr(metadata, 'prompt_token_count', 0)
                output_tokens = getattr(metadata, 'candidates_token_count', 0)
                # Check for cache read tokens (Gemini-specific)
                cached_tokens = getattr(metadata, 'cached_content_input_token_count', 0)
            
            # Fallback for direct dict access
            elif isinstance(response, dict):
                input_tokens = response.get('usage_metadata', {}).get('prompt_token_count', 0)
                output_tokens = response.get('usage_metadata', {}).get('candidates_token_count', 0)
                cached_tokens = response.get('usage_metadata', {}).get('cached_content_input_token_count', 0)
            
            usage = TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens
            )
            
            logger.debug(
                f"Token usage extracted: input={usage.input_tokens}, "
                f"output={usage.output_tokens}, cached={usage.cached_tokens}, "
                f"total_billable={usage.total_tokens}"
            )
            
            return usage
        
        except Exception as e:
            logger.error(f"Failed to extract token usage: {str(e)}")
            # Return zero usage on extraction failure (don't crash)
            return TokenUsage(input_tokens=0, output_tokens=0, cached_tokens=0)
    
    @staticmethod
    def estimate_tokens(text: str, model: str = "gemini-3.1-flash-lite-preview") -> int:
        """
        Estimate token count for text input (rough approximation).
        Actual count will be retrieved from API response.
        
        Rule of thumb: ~4 characters = 1 token (average)
        """
        # More conservative estimate for safety
        return max(1, len(text.split()) // 0.75)
    
    @staticmethod
    def combine_usage(usages: list[TokenUsage]) -> TokenUsage:
        """Combine multiple token usage objects"""
        total_input = sum(u.input_tokens for u in usages)
        total_output = sum(u.output_tokens for u in usages)
        total_cached = sum(u.cached_tokens for u in usages)
        
        return TokenUsage(
            input_tokens=total_input,
            output_tokens=total_output,
            cached_tokens=total_cached
        )
