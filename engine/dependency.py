import json
import hashlib
import logging
import os
import re
import time
from difflib import SequenceMatcher
from typing import List, Dict, Tuple, Optional
from openai import OpenAI
from poly_arb_bot.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

# --- Dependency Cache ---
# Persist LLM results to disk so restarts don't re-analyze the same pairs.
# Cache key = hash of both questions (order-independent).
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dep_cache")
CACHE_TTL_SECONDS = 7 * 86400  # 7 days before re-analyzing

# Model selection — gpt-4o-mini is ~10× cheaper and equally accurate for
# binary classification / logical reasoning tasks.
LLM_MODEL = os.getenv("DEP_LLM_MODEL", "gpt-4o-mini")
LLM_QUOTA_COOLDOWN_SECONDS = int(os.getenv("DEP_LLM_QUOTA_COOLDOWN_SECONDS", "1800"))  # 30 min
LLM_MAX_RETRIES = int(os.getenv("DEP_LLM_MAX_RETRIES", "1"))


def _cache_key(q1: str, q2: str) -> str:
    """Order-independent hash so (A,B) == (B,A)."""
    pair = sorted([q1.strip().lower(), q2.strip().lower()])
    return hashlib.sha256("|".join(pair).encode()).hexdigest()[:20]


class DependencyDetector:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY, max_retries=LLM_MAX_RETRIES) if OPENAI_API_KEY else None
        if not self.client:
            logger.warning("OpenAI API key not set. LLM dependency detection is DISABLED.")
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._cache_hits = 0
        self._cache_misses = 0
        self._llm_disabled_until = 0.0

    # ---- Cache helpers ----

    def _read_cache(self, key: str, allow_stale: bool = False) -> List[Tuple[str, str]] | None:
        """Return cached result or None if miss (or expired unless allow_stale=True)."""
        path = os.path.join(CACHE_DIR, f"{key}.json")
        try:
            if not os.path.exists(path):
                return None
            with open(path, "r") as f:
                data = json.load(f)
            # Check TTL
            if (time.time() - data.get("ts", 0) > CACHE_TTL_SECONDS) and not allow_stale:
                return None
            result = data.get("result")
            if result is None:
                return None
            return [tuple(p) for p in result]
        except Exception:
            return None

    def _write_cache(self, key: str, result: List[Tuple[str, str]], q1: str, q2: str, reasoning: str = ""):
        """Persist an LLM result to disk."""
        path = os.path.join(CACHE_DIR, f"{key}.json")
        try:
            with open(path, "w") as f:
                json.dump({
                    "ts": time.time(),
                    "q1": q1[:120],
                    "q2": q2[:120],
                    "reasoning": reasoning,
                    "result": [list(p) for p in result],
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")

    def get_cache_stats(self) -> Dict[str, int]:
        return {"hits": self._cache_hits, "misses": self._cache_misses}

    def _llm_temporarily_disabled(self) -> bool:
        return time.time() < self._llm_disabled_until

    def _disable_llm_temporarily(self, reason: str):
        self._llm_disabled_until = time.time() + max(LLM_QUOTA_COOLDOWN_SECONDS, 60)
        cooldown = int(max(self._llm_disabled_until - time.time(), 0))
        logger.warning(
            f"LLM temporarily disabled for {cooldown}s due to {reason}. "
            "Using cache/heuristic fallback during cooldown."
        )

    # ---- Conservative non-LLM fallback ----

    @staticmethod
    def _normalize_text(text: str) -> str:
        t = (text or "").strip().lower()
        t = re.sub(r"[^a-z0-9\s$.\-]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    @staticmethod
    def _extract_party_most_seats(text: str) -> Optional[str]:
        m = re.search(r"\bwill\s+(.+?)\s+win\s+the\s+most\s+seats\b", text, flags=re.I)
        if not m:
            return None
        return m.group(1).strip().lower()

    @staticmethod
    def _strip_party_most_seats(text: str) -> str:
        return re.sub(r"\bwill\s+.+?\s+win\s+the\s+most\s+seats\b", "will PARTY win the most seats", text, flags=re.I)

    @staticmethod
    def _extract_threshold_rule(text: str) -> Optional[Tuple[str, float, str]]:
        """
        Return (direction, threshold, stem) for simple threshold markets.
        direction in {"gt","lt"}.
        """
        t = DependencyDetector._normalize_text(text)
        patterns = [
            (r"\b(above|over|more than|greater than)\s+\$?(\d+(?:\.\d+)?)\b", "gt"),
            (r"\b(at least)\s+\$?(\d+(?:\.\d+)?)\b", "gt"),
            (r"\b(below|under|less than)\s+\$?(\d+(?:\.\d+)?)\b", "lt"),
            (r"\b(at most)\s+\$?(\d+(?:\.\d+)?)\b", "lt"),
        ]
        for pat, direction in patterns:
            m = re.search(pat, t)
            if not m:
                continue
            try:
                val = float(m.group(2))
            except Exception:
                continue
            stem = re.sub(pat, " THRESH ", t)
            stem = re.sub(r"\b(20\d{2})\b", " YEAR ", stem)
            stem = re.sub(r"\s+", " ", stem).strip()
            return direction, val, stem
        return None

    def _heuristic_dependency(self, question_a: str, question_b: str) -> List[Tuple[str, str]]:
        """
        Very conservative dependency detector used only when LLM is unavailable.
        Returns [] unless dependency is obvious.
        """
        qa = self._normalize_text(question_a)
        qb = self._normalize_text(question_b)
        if not qa or not qb:
            return []

        # Exact same question -> perfect equivalence.
        if qa == qb:
            return [("YES", "YES"), ("NO", "NO")]

        # "Will X win the most seats" vs "Will Y win the most seats"
        # in the same election context: both cannot be YES simultaneously.
        party_a = self._extract_party_most_seats(question_a)
        party_b = self._extract_party_most_seats(question_b)
        if party_a and party_b and party_a != party_b:
            core_a = self._strip_party_most_seats(qa)
            core_b = self._strip_party_most_seats(qb)
            sim = SequenceMatcher(None, core_a, core_b).ratio()
            if sim >= 0.80:
                return [("YES", "NO"), ("NO", "YES"), ("NO", "NO")]

        # Threshold implication (same underlying stem + same direction).
        rule_a = self._extract_threshold_rule(question_a)
        rule_b = self._extract_threshold_rule(question_b)
        if rule_a and rule_b:
            dir_a, val_a, stem_a = rule_a
            dir_b, val_b, stem_b = rule_b
            if dir_a == dir_b and SequenceMatcher(None, stem_a, stem_b).ratio() >= 0.82:
                impossible = None
                if dir_a == "gt":
                    if val_a > val_b:
                        impossible = ("YES", "NO")  # A_yes implies B_yes
                    elif val_b > val_a:
                        impossible = ("NO", "YES")  # B_yes implies A_yes
                elif dir_a == "lt":
                    if val_a < val_b:
                        impossible = ("YES", "NO")  # A_yes implies B_yes
                    elif val_b < val_a:
                        impossible = ("NO", "YES")  # B_yes implies A_yes

                if impossible:
                    all_combos = [("YES", "YES"), ("YES", "NO"), ("NO", "YES"), ("NO", "NO")]
                    return [c for c in all_combos if c != impossible]

        return []

    def _fallback_without_llm(self, key: str, question_a: str, question_b: str, reason: str) -> List[Tuple[str, str]]:
        # 1) stale cache is still better than no signal when LLM is down.
        stale = self._read_cache(key, allow_stale=True)
        if stale is not None:
            logger.warning(
                f"LLM fallback ({reason}): using STALE cache for '{question_a[:40]}' vs '{question_b[:40]}'"
            )
            return stale

        # 2) conservative deterministic heuristic as final fallback.
        heuristic = self._heuristic_dependency(question_a, question_b)
        if heuristic:
            logger.warning(
                f"LLM fallback ({reason}): heuristic dependency with {len(heuristic)} combos "
                f"for '{question_a[:40]}' vs '{question_b[:40]}'"
            )
            self._write_cache(key, heuristic, question_a, question_b, f"heuristic_fallback:{reason}")
        else:
            logger.warning(
                f"LLM fallback ({reason}): no safe heuristic dependency "
                f"for '{question_a[:40]}' vs '{question_b[:40]}'"
            )
        return heuristic

    # ---- Main analysis ----

    def analyze_market_pair(self, market_a: Dict, market_b: Dict) -> List[Tuple[str, str]]:
        """
        Ask LLM if there is a logical dependency between two markets.
        Returns a list of VALID outcome pairs (e.g. [("YES", "YES"), ("NO", "NO"), ...]).
        Returns empty list if markets are independent (all 4 combos valid) or on error.

        Results are cached to disk to avoid repeated LLM calls on restarts.
        """
        question_a = market_a.get("question", "Unknown Question A")
        question_b = market_b.get("question", "Unknown Question B")

        # --- Check cache first ---
        key = _cache_key(question_a, question_b)
        cached = self._read_cache(key)
        if cached is not None:
            self._cache_hits += 1
            if cached:
                logger.info(f"CACHE HIT (dep): '{question_a[:40]}' vs '{question_b[:40]}' → {len(cached)} combos")
            else:
                logger.debug(f"CACHE HIT (indep): '{question_a[:40]}' vs '{question_b[:40]}'")
            return cached
        self._cache_misses += 1

        if not self.client:
            return self._fallback_without_llm(key, question_a, question_b, reason="no_openai_client")
        if self._llm_temporarily_disabled():
            return self._fallback_without_llm(key, question_a, question_b, reason="quota_cooldown")

        # --- LLM call ---
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
                model=LLM_MODEL,
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
            reasoning = result.get("reasoning", "No reasoning provided")
            
            # If markets are independent, return empty (no arbitrage opportunity)
            if not result.get("dependent", True):
                logger.info(f"Markets are INDEPENDENT: '{question_a[:50]}' vs '{question_b[:50]}'")
                self._write_cache(key, [], question_a, question_b, reasoning)
                return []
            
            valid_outcomes = result.get("valid_outcomes", [])
            
            # Validate the response
            if not valid_outcomes or not isinstance(valid_outcomes, list):
                self._write_cache(key, [], question_a, question_b, reasoning)
                return []
            
            # If all 4 combos are present, they're independent
            if len(valid_outcomes) >= 4:
                logger.info("Markets have all 4 combos valid (independent).")
                self._write_cache(key, [], question_a, question_b, reasoning)
                return []
            
            # Convert list of lists to list of tuples
            valid_tuples = []
            for pair in valid_outcomes:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    a, b = str(pair[0]).upper(), str(pair[1]).upper()
                    if a in ("YES", "NO") and b in ("YES", "NO"):
                        valid_tuples.append((a, b))
            
            if not valid_tuples:
                self._write_cache(key, [], question_a, question_b, reasoning)
                return []
            
            logger.info(f"Dependency detected ({len(valid_tuples)} valid combos): {reasoning}")
            self._write_cache(key, valid_tuples, question_a, question_b, reasoning)
            return valid_tuples
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}")
            return self._fallback_without_llm(key, question_a, question_b, reason="json_parse_error")
        except Exception as e:
            logger.error(f"Error calling LLM for dependency detection: {e}")
            msg = str(e).lower()
            if "insufficient_quota" in msg or "quota" in msg:
                self._disable_llm_temporarily("insufficient_quota")
            return self._fallback_without_llm(key, question_a, question_b, reason="llm_error")
