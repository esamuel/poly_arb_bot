import json
import logging
from typing import List, Dict, Any, Tuple
from openai import OpenAI
from poly_arb_bot.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)


class DependencyDetector:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
        if not self.client:
            logger.warning("OpenAI API key not set. LLM dependency detection is DISABLED.")
        
    def analyze_market_pair(self, market_a: Dict, market_b: Dict) -> List[Tuple[str, str]]:
        """
        Ask LLM if there is a logical dependency between two markets.
        Returns a list of VALID outcome pairs (e.g. [("YES", "YES"), ("NO", "NO"), ...]).
        Returns empty list if markets are independent (all 4 combos valid) or on error.
        """
        if not self.client:
            logger.warning("No OpenAI client. Skipping dependency analysis.")
            return []

        question_a = market_a.get("question", "Unknown Question A")
        question_b = market_b.get("question", "Unknown Question B")
        
        prompt = f"""Analyze the logical relationship between these two prediction markets:

Market A: {question_a}
Market B: {question_b}

Determine which combinations of outcomes (YES/NO) are logically POSSIBLE.

Rules:
- If Market A happening makes Market B IMPOSSIBLE, remove that combination.
- If A implies B (A=YES means B must be YES), then (YES, NO) is impossible.
- If the markets are completely unrelated/independent, return ALL 4 combinations.
- Be conservative: only remove a combination if it's TRULY logically impossible.

Output ONLY a valid JSON object in this format:
{{
    "valid_outcomes": [
        ["YES", "YES"],
        ["YES", "NO"],
        ["NO", "YES"], 
        ["NO", "NO"] 
    ],
    "dependent": true,
    "reasoning": "Brief explanation of the logical relationship."
}}

Set "dependent" to false if all 4 combinations are valid (markets are independent).
Remove impossible combinations from the valid_outcomes list."""
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a logic expert analyzing prediction markets for arbitrage opportunities. Be precise and conservative. Only declare a dependency when there is a clear logical implication."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,  # Low temperature for consistency
                timeout=15
            )
            
            content = response.choices[0].message.content
            if not content:
                logger.error("LLM returned empty content.")
                return []
                
            result = json.loads(content)
            
            # If markets are independent, return empty (no arbitrage opportunity)
            if not result.get("dependent", True):
                logger.info(f"Markets are INDEPENDENT: '{question_a[:50]}' vs '{question_b[:50]}'")
                return []
            
            valid_outcomes = result.get("valid_outcomes", [])
            
            # Validate the response
            if not valid_outcomes or not isinstance(valid_outcomes, list):
                return []
            
            # If all 4 combos are present, they're independent
            if len(valid_outcomes) >= 4:
                logger.info(f"Markets have all 4 combos valid (independent).")
                return []
            
            # Convert list of lists to list of tuples
            valid_tuples = []
            for pair in valid_outcomes:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    a, b = str(pair[0]).upper(), str(pair[1]).upper()
                    if a in ("YES", "NO") and b in ("YES", "NO"):
                        valid_tuples.append((a, b))
            
            if not valid_tuples:
                return []
            
            reasoning = result.get("reasoning", "No reasoning provided")
            logger.info(f"Dependency detected ({len(valid_tuples)} valid combos): {reasoning}")
            return valid_tuples
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}")
            return []
        except Exception as e:
            logger.error(f"Error calling LLM for dependency detection: {e}")
            return []
