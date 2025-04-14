# --- START OF FILE app/services/expertise_analyzer.py ---
import logging
from typing import List, Tuple, Dict
from collections import Counter
from ..services.memory_manager import get_all_memories, extract_keywords # Use memory manager functions

log = logging.getLogger(__name__)

def calculate_expertise_scores(user_id: int, min_mentions: int = 3, top_n: int = 25) -> List[Tuple[str, float]]:
    """
    Calculates expertise scores based on keyword frequency in user's memory.
    Returns list of (topic, score) tuples.

    NOTE: This is a BASIC placeholder. Replace with more sophisticated scoring.
    """
    log.debug(f"User {user_id}: Calculating expertise scores (basic frequency).")
    all_keywords = []
    try:
        # Consider performance: Limit memory retrieval if history is vast
        memories = get_all_memories(user_id, limit=1000) # Analyze latest 1000 entries

        if not memories: log.debug(f"User {user_id}: No memories for expertise."); return []

        for item in memories:
            keywords_str = item.get('metadata', {}).get('keywords')
            if keywords_str: all_keywords.extend(keywords_str.split(','))
            # else: all_keywords.extend(extract_keywords(item.get('text',''), max_keywords=5)) # Less efficient fallback

        if not all_keywords: log.debug(f"User {user_id}: No keywords extracted."); return []

        keyword_counts = Counter(kw for kw in all_keywords if kw) # Count non-empty keywords
        expertises = [(topic, float(count)) for topic, count in keyword_counts.most_common(top_n * 2) if count >= min_mentions]
        expertises = expertises[:top_n] # Limit final list
        log.info(f"User {user_id}: Identified {len(expertises)} potential expertise areas.")
        return expertises

    except Exception as e:
        log.error(f"User {user_id}: Failed during expertise calculation: {e}", exc_info=True)
        return []
# --- END OF FILE app/services/expertise_analyzer.py ---