from typing import Literal

from google import genai
from pydantic import BaseModel, Field

from app.champions import CHAMPIONS


class QueryContext(BaseModel):
    player_champion: str | None
    enemy_champion: str | None
    requested_champions: list[str] = Field(default_factory=list)
    role: Literal["Top", "Jungle", "Mid", "ADC", "Support"] | None
    query_type: Literal["build", "matchup", "strategy", "stats", "general"]
    ranking_metric: Literal["win_rate", "pick_rate", "ban_rate"] | None = None
    ranking_count: int | None = None


client = genai.Client()


def parse_query(message: str, recent_history: list[dict] | None = None) -> QueryContext:
    history_text = ""

    if recent_history:
        for item in recent_history[-6:]:
            history_text += f'{item["role"]}: {item["content"]}\n'

    champion_list = ", ".join(CHAMPIONS)

    prompt = f"""
You are an information extractor for a League of Legends coaching assistant.

Extract these fields:

- player_champion
- enemy_champion
- requested_champions
- role
- query_type
- ranking_metric
- ranking_count

Valid roles:
Top, Jungle, Mid, ADC, Support

Valid query types:
build, matchup, strategy, stats, general

Valid ranking metrics:
win_rate, pick_rate, ban_rate

Normalized champion list:
{champion_list}

FIELD DEFINITIONS

player_champion:
The champion the user is playing or primarily asking coaching advice about.

enemy_champion:
The opposing champion in a direct matchup.

requested_champions:
A list of champions the user is requesting information about collectively.

ranking_metric and ranking_count:
Use these only when the user asks for a role-wide ranking, such as "top 3
midlaners", "best supports by win rate", or "highest pick-rate ADCs".

- ranking_metric is the requested statistic. For "top", "best", "strongest",
  "tier", or "meta" without a stated statistic, use win_rate.
- ranking_count is the requested number. Use 3 for "top 3". If no number is
  stated, use 5. Do not use a number larger than 10.
- A role-wide ranking has no requested_champions unless named champions are
  explicitly part of the question.

Examples:
"top 3 midlaners this patch"
→ role = "Mid", query_type = "stats", ranking_metric = "win_rate", ranking_count = 3

"best supports by win rate"
→ role = "Support", query_type = "stats", ranking_metric = "win_rate", ranking_count = 5

"highest pick-rate ADCs"
→ role = "ADC", query_type = "stats", ranking_metric = "pick_rate", ranking_count = 5

"What are Jinx and Kaisa's win rates?"
→ requested_champions = ["Jinx", "Kaisa"]

"Compare Ahri, Syndra and Orianna"
→ requested_champions = ["Ahri", "Syndra", "Orianna"]

If the user says things like:
"their win rates"
"which of those is strongest?"
"compare those champions"
"which one has the highest pick rate?"

use the recent conversation to determine which champions "they", "those",
or "which one" refers to.

Do NOT put the direct matchup enemy into requested_champions unless the user
is explicitly asking for statistics or a comparison across multiple champions.

IMPORTANT CONTEXT RULES

- Use the recent conversation to understand follow-up questions.
- Preserve the previously established player champion unless the current
  message clearly changes it.
- Preserve the previously established role unless the current message clearly
  changes it.
- Preserve the previously established enemy champion unless the current
  message introduces a new opponent.
- If the current message introduces a new opponent, replace only enemy_champion.
- Do not accidentally turn the previous enemy champion into player_champion.
- If the user explicitly changes their champion, update player_champion.
- For plural references such as "they", "them", "those", or "their", inspect
  previous assistant and user messages to determine the relevant champions.
- If information cannot be inferred, use null for singular fields and an empty
  list for requested_champions.
- Use ONLY champion names from the normalized champion list.
- Preserve normalized champion spelling exactly.

QUERY TYPES

build:
Builds, items, runes, skill order.

matchup:
One champion versus another.

strategy:
Gameplay, laning, mechanics, macro, positioning, wave management.

stats:
Win rate, pick rate, ban rate, statistics, rankings, tier or meta strength.

general:
Anything else related to League of Legends.

Recent conversation:
{history_text}

Current user message:
{message}
"""

    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": QueryContext
        }
    )

    context = response.parsed

    if context.player_champion not in CHAMPIONS:
        context.player_champion = None

    if context.enemy_champion not in CHAMPIONS:
        context.enemy_champion = None

    context.requested_champions = [champion for champion in context.requested_champions if champion in CHAMPIONS]

    if context.ranking_count is not None:
        context.ranking_count = min(max(context.ranking_count, 1), 10)

    return context
