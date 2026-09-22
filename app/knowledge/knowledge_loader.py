from pathlib import Path

DIR = Path(__file__).parent / "season_16"

TOPICS = {
    "macro": "macro.md",
    "role_quests": "role_quests.md",
    "turret_plates": "turret_plates.md",
    "objectives": "objectives.md",
    "faelights": "faelights.md",
    "bounties": "bounties.md",
}


def load_relevant_knowledge(topics: list[str]) -> str:
    """
    Combine knowledge excerpts for the requested topics.
    """
    content = []

    for topic in topics:
        filename = TOPICS.get(topic)

        if filename is not None:
            knowledge = load_knowledge_file(filename)
            content.append(f"=== KNOWLEDGE SOURCE: {topic.upper()} ===\n\n{knowledge}")
    return "\n\n".join(content)


def load_knowledge_file(filename: str) -> str:
    """
    Read a knowledge file when it exists.
    """
    path = DIR / filename
    return path.read_text(encoding="utf-8")
