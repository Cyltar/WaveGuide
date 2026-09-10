from typing import Literal

from google import genai
from pydantic import BaseModel, Field

from app.champions import CHAMPIONS

KnowledgeTopic = Literal[
    "macro",
    "role_quests",
    "turret_plates",
    "objectives",
    "faelights",
    "bounties"
]

class QueryContext(BaseModel):
    player_champion: str | None
    enemy_champion: str | None
    requested_champions: list[str] = Field(default_factory=list)
    role: Literal["Top", "Jungle", "Mid", "ADC", "Support"] | None
    query_type: Literal["build", "matchup", "strategy", "stats", "general"]
    ranking_metric: Literal["win_rate", "pick_rate", "ban_rate"] | None = None
    ranking_count: int | None = None
    knowledge_topics: list[KnowledgeTopic] = Field(default_factory=list)

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
- knowledge_topics

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
- knowledge_topics should describe what is needed for the CURRENT question,
  while using recent conversation context to resolve references.
- Do not automatically preserve previous knowledge_topics if the new
  question no longer needs them.
- If the current message is a follow-up that depends on an earlier
  mechanic, select the necessary topic again.

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

KNOWLEDGE TOPICS

knowledge_topics determines which current Season 16 knowledge files
are needed to answer the user's CURRENT question.

Valid knowledge topics:

macro
role_quests
turret_plates
objectives
faelights
bounties

Use an empty list if no current Season 16 knowledge file is needed.

Only select topics that are directly useful for answering the current
question. Do NOT select every potentially related topic.

TOPIC DEFINITIONS

macro:
General macro decision-making involving rotations, tempo, recalls,
wave states, side-laning, cross-map trades, grouping, map pressure,
numbers advantages, or comparing multiple possible plays.

role_quests:
Questions involving Top, Mid, Bot, Jungle, or Support quest progression,
quest rewards, quest completion, roaming penalties, or how role quests
affect macro decisions.

turret_plates:
Questions involving turrets, turret plates, Tier 1/Tier 2/Tier 3
structures, inhibitors, Nexus turrets, Crystalline Overgrowth,
Demolish, turret gold, or deciding whether turret pressure is worth
more than another play.

objectives:
Questions involving Dragons, Dragon Soul, Void Grubs, Rift Herald,
Baron Nashor, Elder Dragon, objective timers, objective setup,
objective trading, Smite contests, or choosing between objectives.

faelights:
Questions involving Faelights, ward locations, side-lane safety,
vision gaps, Control Wards, objective vision, gank safety, or
Season 16 vision mechanics.

bounties:
Questions involving champion shutdowns, champion bounty values,
objective bounties, comeback gold, bounty timers, trading structures
during bounty windows, or protecting a large shutdown.

KNOWLEDGE TOPIC SELECTION RULES

- Select the SMALLEST set of topics needed to answer the question well.
- Do not select a topic merely because it is generally related to League.
- Select "macro" only when the user is asking for a decision, rotation,
  map movement, resource tradeoff, wave/tempo decision, side-lane
  decision, or broader macro reasoning.
- For simple factual mechanic questions, select only the specific
  factual topic and omit "macro".
- Select multiple topics when the user is explicitly comparing systems.
- Use recent conversation context when the current message is a follow-up.
- If none of the Season 16 knowledge files are relevant, return an empty list.
- Do not select knowledge topics for general champion gameplay advice unless
  the answer specifically depends on a current Season 16 system contained in
  the knowledge files.
- Champion abilities, matchup strategy, trading patterns, positioning, and
  general champion gameplay do not by themselves require knowledge_topics.
- Select a knowledge topic when current game-system information would
  materially affect the answer.
  
KNOWLEDGE TOPIC EXAMPLES

"What does a Faelight do?"
→ knowledge_topics = ["faelights"]

"How do Top role quests work?"
→ knowledge_topics = ["role_quests"]

"How much is a Tier 2 plate worth?"
→ knowledge_topics = ["turret_plates"]

"When does Baron spawn?"
→ knowledge_topics = ["objectives"]

"Why does Jinx have a bounty even though she is 0/0?"
→ knowledge_topics = ["bounties"]

"Should I stay Top for two Tier 2 plates or rotate to third Dragon?"
→ knowledge_topics = [
    "macro",
    "turret_plates",
    "objectives",
    "role_quests"
]

"Should I stay Top for plates or rotate to Dragon if objective bounties are active?"
→ knowledge_topics = [
    "macro",
    "turret_plates",
    "objectives",
    "role_quests",
    "bounties"
]

"How far can I push Bot if I have the side Faelight warded?"
→ knowledge_topics = [
    "macro",
    "faelights"
]

"Should I use Herald Mid 60 seconds before Dragon?"
→ knowledge_topics = [
    "macro",
    "objectives",
    "turret_plates"
]

"Should Support roam at level 3?"
→ knowledge_topics = [
    "macro",
    "role_quests"
]

"How do I play Ahri into Yone?"
→ knowledge_topics = []

"What is Ahri's current win rate?"
→ knowledge_topics = []

"Compare Ahri and Syndra's win rates."
→ knowledge_topics = []

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
