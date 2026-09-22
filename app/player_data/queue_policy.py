"""Shared queue eligibility for WaveGuide player analysis."""

SUPPORTED_ANALYSIS_QUEUES = {
    400: "Normal Draft", 420: "Ranked Solo/Duo", 440: "Ranked Flex", 480: "Swiftplay",
}
SUPPORTED_ANALYSIS_QUEUE_IDS = frozenset(SUPPORTED_ANALYSIS_QUEUES)
SWIFTPLAY_LIMITATION = (
    "Swiftplay economy, objectives and pacing differ from Draft/Ranked. Fixed phase labels and gold thresholds "
    "are not calibrated for Swiftplay; do not use them as benchmarks for mistakes or recall/item timing. "
    "Wave estimates, low-farm review and gold-swing thresholds are omitted for this queue."
)


class UnsupportedAnalysisQueueError(ValueError):
    """A match belongs to a queue outside the supported allowlist."""


def is_supported_analysis_match(match: dict) -> bool:
    """
    Return whether metadata contains an explicitly supported integer queue ID.
    """
    queue_id = match.get("info", {}).get("queueId")
    return type(queue_id) is int and queue_id in SUPPORTED_ANALYSIS_QUEUE_IDS


def require_supported_analysis_match(match: dict) -> None:
    """
    Reject unsupported or missing queues before analysis or timeline retrieval.
    """
    if not is_supported_analysis_match(match):
        raise UnsupportedAnalysisQueueError(
            "That match is from a game mode WaveGuide does not currently analyze. "
            "WaveGuide supports Draft, Ranked Solo/Duo, Ranked Flex, and Swiftplay on Summoner's Rift."
        )


def queue_search_metadata() -> dict:
    """
    Initialize lightweight queue eligibility counts for a new search.
    """
    return {"supported_queue_ids": sorted(SUPPORTED_ANALYSIS_QUEUE_IDS),
            "unsupported_matches_skipped": 0, "unsupported_queue_counts": {}}


def skip_unsupported_match(match: dict, metadata: dict) -> bool:
    """
    Count an unsupported metadata record without treating it as a matching game.
    """
    if is_supported_analysis_match(match):
        return False
    metadata["unsupported_matches_skipped"] += 1
    key = str(match.get("info", {}).get("queueId", "unknown"))
    counts = metadata["unsupported_queue_counts"]
    counts[key] = counts.get(key, 0) + 1
    return True
