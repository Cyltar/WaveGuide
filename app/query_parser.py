import re
from typing import Literal

from google import genai
from pydantic import BaseModel, Field

from app.champions import CHAMPIONS
from app.player_data.analysis_service import normalize_selector_champion, SpecificMatchSelectionError


KnowledgeTopic = Literal["macro", "role_quests", "turret_plates", "objectives", "faelights", "bounties"]

PlayerAnalysisMode = Literal["specific_game", "recent_games", "champion_games"]

PlayerAnalysisSeasonScope = Literal["current", "previous", "all", "unspecified"]


class PlayerAnalysisRequest(BaseModel):
    requested: bool = False
    mode: PlayerAnalysisMode | None = None
    champion: str | None = None
    # Preserve exactly what the user requested.
    # app.py performs the actual 1..20 validation.
    game_count: int | None = None
    match_id: str | None = None
    specific_game_index: int | None = Field(default=None, strict=True)
    kills: int | None = Field(default=None, strict=True)
    deaths: int | None = Field(default=None, strict=True)
    assists: int | None = Field(default=None, strict=True)
    opponent: str | None = None
    all_games_requested: bool = False
    season_scope: PlayerAnalysisSeasonScope = "unspecified"
    # Optional Riot ID supplied in the current message or
    # carried forward from recent conversation context.
    riot_game_name: str | None = None
    riot_tag_line: str | None = None


class QueryContext(BaseModel):
    player_champion: str | None
    enemy_champion: str | None
    requested_champions: list[str] = Field(default_factory=list)
    role: Literal["Top", "Jungle", "Mid", "ADC", "Support"] | None
    query_type: Literal["build", "matchup", "strategy", "stats", "general"]
    ranking_metric: Literal["win_rate", "pick_rate", "ban_rate"] | None = None
    ranking_count: int | None = None
    knowledge_topics: list[KnowledgeTopic] = Field(default_factory=list)
    player_analysis: PlayerAnalysisRequest = Field(default_factory=PlayerAnalysisRequest)


client = genai.Client()


def champion_mentions(text: str) -> list[str]:
    """
    Find canonical champion names while tolerating common spacing and apostrophe variations.
    """
    matches = []
    for champion in CHAMPIONS:
        pattern = r"(?<!\w)" + r"[\s'’.\-]*".join(re.escape(letter) for letter in champion) + r"(?!\w)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            matches.append((match.start(), champion))
    return [champion for _, champion in sorted(matches)]


def apply_explicit_game_selector(message: str, request: PlayerAnalysisRequest) -> None:
    """
    Preserve explicit singular, ordinal, and KDA intent after semantic query extraction.
    """
    if not request.requested:
        return
    text = re.sub(r"\S+#\S+", "", message)
    match_id = re.search(r"\b[A-Z][A-Z0-9]*_\d+\b", text, re.IGNORECASE)
    if match_id:
        request.mode = "specific_game"
        request.match_id = match_id.group().upper()
        request.game_count = None
        return
    request.match_id = None

    kda = re.search(r"(?<![\w/])(-?\d+)\s*/\s*(-?\d+)\s*/\s*(-?\d+)(?![\w/])", text)
    versus = re.search(r"\b(?:against|versus|vs\.?)\s+", text, re.IGNORECASE)
    player_text = text[:versus.start()] if versus else text
    champions = champion_mentions(player_text)
    enemies = champion_mentions(text[versus.end():]) if versus else []
    multiple = re.search(r"\b(?:last|recent|latest)\s+(\d+)\s+.*?\b(?:games|matches)\b", text, re.IGNORECASE)
    if multiple and not kda:
        request.mode = "champion_games" if champions else "recent_games"
        request.game_count = int(multiple.group(1))
        request.champion = champions[0] if champions else None
        request.specific_game_index = None
        request.kills = request.deaths = request.assists = None
        request.opponent = None
        return

    if not (re.search(r"\b(?:game|match)\b", text, re.IGNORECASE) or kda):
        return
    request.mode = "specific_game"
    request.game_count = None
    if champions:
        request.champion = champions[0]
    if enemies:
        request.opponent = enemies[0]
    if kda:
        request.kills, request.deaths, request.assists = map(int, kda.groups())

    game_ordinal_suffix = r"(?=\s+(?:most\s+recent\b|(?:[\w'’]+\s+){0,2}(?:game|match)\b))"
    numeric = re.search(r"(?<!\w)(-?\d+)(?:st|nd|rd|th)\b" + game_ordinal_suffix, text, re.IGNORECASE)
    words = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
             "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
             "eighteenth", "nineteenth", "twentieth"]
    ordinals = {word: index for index, word in enumerate(words, 1)}
    ordinals["zeroth"] = 0
    for tens, cardinal, ordinal_word in [(20, "twenty", "twentieth"), (30, "thirty", "thirtieth"),
                                        (40, "forty", "fortieth"), (50, "fifty", "fiftieth"),
                                        (60, "sixty", "sixtieth"), (70, "seventy", "seventieth"),
                                        (80, "eighty", "eightieth"), (90, "ninety", "ninetieth")]:
        ordinals[ordinal_word] = tens
        for unit, word in enumerate(words[:9], 1):
            ordinals[f"{cardinal} {word}"] = tens + unit
    ordinals["hundredth"] = 100
    ordinal = re.search(r"\b(" + "|".join(sorted(ordinals, key=len, reverse=True)) + r")\b" + game_ordinal_suffix,
                        text.replace("-", " "), re.IGNORECASE)
    if numeric:
        request.specific_game_index = int(numeric.group(1))
    elif re.search(r"\bprevious\s+(?!season\b)|\bgame before (?:my |the )?last game\b", text, re.IGNORECASE):
        request.specific_game_index = 2
    elif ordinal:
        request.specific_game_index = ordinals[ordinal.group(1).lower()]
    elif re.search(r"\b(?:recent|latest|last)\b|\bjust played\b", text, re.IGNORECASE):
        request.specific_game_index = 1
    else:
        request.specific_game_index = None


def parse_query(message: str, recent_history: list[dict] | None = None) -> QueryContext:
    """
    Extract structured query context from the message and chat history.
    """
    history_text = ""

    if recent_history:
        for item in recent_history[-10:]:
            history_text += f'{item["role"]}: ' f'{item["content"]}\n'
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

- player_analysis



Valid roles:

Top, Jungle, Mid, ADC, Support



Valid query types:

build, matchup, strategy, stats, general



Valid ranking metrics:

win_rate, pick_rate, ban_rate



Normalized champion list:

{champion_list}



==================================================

GENERAL FIELD DEFINITIONS

==================================================



player_champion:

The champion the user is playing or primarily asking coaching advice about.



enemy_champion:

The opposing champion in a direct matchup.



requested_champions:

A list of champions the user is requesting information about collectively.



ranking_metric and ranking_count:

Use these only when the user asks for a role-wide ranking.



Examples:



"top 3 midlaners this patch"

→ role = "Mid"

→ query_type = "stats"

→ ranking_metric = "win_rate"

→ ranking_count = 3



"best supports by win rate"

→ role = "Support"

→ query_type = "stats"

→ ranking_metric = "win_rate"

→ ranking_count = 5



"highest pick-rate ADCs"

→ role = "ADC"

→ query_type = "stats"

→ ranking_metric = "pick_rate"

→ ranking_count = 5



"What are Jinx and Kaisa's win rates?"

→ requested_champions = ["Jinx", "Kaisa"]



For role-wide rankings:



- For "top", "best", "strongest", "tier", or "meta" without a stated

  statistic, use win_rate.

- If no number is stated, ranking_count = 5.

- Do not use a ranking_count greater than 10.



==================================================

PLAYER ANALYSIS

==================================================



player_analysis is used when the user wants WaveGuide to inspect THEIR OWN

Riot match history or gameplay.



WaveGuide supports three modes:



1. specific_game

2. recent_games

3. champion_games



--------------------------------------------------

WHEN PLAYER ANALYSIS IS REQUESTED

--------------------------------------------------



Set:



player_analysis.requested = true



when the user wants analysis of their own gameplay or match history.



Examples:



"Analyze my games."



"Analyze my recent games."



"Analyze my last game."



"Analyze my last 10 games."



"Analyze how I play Yunara."



"What are my weaknesses?"



"What are my weaknesses on Yunara?"



"Why do I keep dying?"



"Analyze my games, my Riot ID is Cessereendya#7944."



Do NOT activate player analysis for general champion coaching.



Examples:



"How do I play Yunara?"

→ requested = false



"How should Yunara play into Nautilus?"

→ requested = false



"What are Yunara's weaknesses?"

→ requested = false



The distinction between "my weaknesses" and "Yunara's weaknesses" is

important.



--------------------------------------------------

MODE: specific_game

--------------------------------------------------



Use:



mode = "specific_game"



when ONE personal game is requested.



Examples:



"Analyze my last game."



"Analyze my latest match."



"Analyze the game I just played."



"Why did I lose my last game?"



"Analyze NA1_123456789."



If an explicit Riot match ID is supplied, preserve it in:



match_id



Never invent a match ID.



--------------------------------------------------

MODE: recent_games

--------------------------------------------------



Use:



mode = "recent_games"



when the user wants multiple personal games analyzed without restricting the

request to one champion.



Examples:



"Analyze my games."



"Analyze my recent games."



"How have I been playing lately?"



"What are my biggest weaknesses?"



"Analyze my last 10 games."



If no number is supplied:



game_count = null



The application will default to 20.



If a number is supplied, preserve it exactly.



"Analyze my last 7 games."

→ game_count = 7



"Analyze my last 100 games."

→ game_count = 100



DO NOT clamp player-analysis game counts.



--------------------------------------------------

MODE: champion_games

--------------------------------------------------



Use:



mode = "champion_games"



when the user wants their personal performance on a specific champion.



Examples:



"Analyze how I play Yunara."



"What are my weaknesses on Yunara?"



"Why do I keep dying on Yunara?"



"Analyze my last 10 Yunara games."



Set:



player_analysis.champion



to the normalized champion name.



When appropriate, also set:



player_champion



to that champion.



--------------------------------------------------

RIOT ID

--------------------------------------------------



A Riot ID has:



Game Name#Tag Line



Example:



Cessereendya#7944



If the user explicitly supplies a Riot ID for personal analysis:



- riot_game_name = the part before #

- riot_tag_line = the part after #



Do not include the # in either field.



Example:



"Analyze my games, my Riot ID is Cessereendya#7944."



→ requested = true

→ mode = "recent_games"

→ riot_game_name = "Cessereendya"

→ riot_tag_line = "7944"



Example:



"Analyze my last 10 Yunara games. Riot ID: Cessereendya#7944"



→ requested = true

→ mode = "champion_games"

→ champion = "Yunara"

→ game_count = 10

→ riot_game_name = "Cessereendya"

→ riot_tag_line = "7944"



Preserve the user's Game Name spelling.



--------------------------------------------------

RIOT ID IN FOLLOW-UP QUESTIONS

--------------------------------------------------



Use recent conversation context for personal-analysis follow-ups.



If a Riot ID was supplied earlier in THIS conversation and the current

message still requires analysis of that person's gameplay, reuse the most

recent Riot ID unless the user explicitly supplies another one.



Example:



Previous:

"Analyze my last 5 games, my Riot ID is Cessereendya#7944."



Current:

"What are my biggest weaknesses?"



→ player_analysis.requested = true

→ riot_game_name = "Cessereendya"

→ riot_tag_line = "7944"



Example:



Previous:

"Analyze my Yunara games, Cessereendya#7944."



Current:

"What about my farming?"



→ player_analysis.requested = true

→ mode = "champion_games"

→ champion = "Yunara"

→ riot_game_name = "Cessereendya"

→ riot_tag_line = "7944"



Example:



Previous:

"Analyze my games, Cessereendya#7944."



Current:

"Analyze my last 3 Xayah games."



→ player_analysis.requested = true

→ mode = "champion_games"

→ champion = "Xayah"

→ game_count = 3

→ riot_game_name = "Cessereendya"

→ riot_tag_line = "7944"



If the user supplies a NEW Riot ID, use the new one.



Example:



Previous:

"Analyze my games, Cessereendya#7944."



Current:

"Now analyze TestPlayer#NA1."



→ riot_game_name = "TestPlayer"

→ riot_tag_line = "NA1"



Do NOT carry a Riot ID into an unrelated general League question.



Example:



Previous:

"Analyze my games, Cessereendya#7944."



Current:

"When does Baron spawn?"



→ player_analysis.requested = false

→ riot_game_name = null

→ riot_tag_line = null



--------------------------------------------------

GAME COUNT

--------------------------------------------------



WaveGuide can analyze at most 20 games per request.



However, parsing MUST preserve the number the user actually requested.



Examples:



"Analyze 5 games."

→ game_count = 5



"Analyze 20 games."

→ game_count = 20



"Analyze 100 games."

→ game_count = 100



DO NOT convert 100 to 20.



The application validates the count later.



--------------------------------------------------

ALL / UNBOUNDED REQUESTS

--------------------------------------------------



Set:



all_games_requested = true



for requests such as:



"Analyze all my games."



"Analyze every game I've played."



"Analyze my entire match history."



"Analyze all my Yunara games."



"Analyze all 100 of my Yunara games."



If an explicit number exists, preserve it.



--------------------------------------------------

SEASON SCOPE

--------------------------------------------------



WaveGuide player analysis supports only the current League season.



Set:



season_scope = "current"



for requests explicitly referring to the current season or Season 16.



Set:



season_scope = "previous"



for requests such as:



"last season"

"previous season"

"Season 15"



Set:



season_scope = "all"



for:



"all seasons"

"lifetime"

"my entire League history"



Otherwise:



season_scope = "unspecified"



Unspecified does NOT mean all seasons.



--------------------------------------------------

PLAYER ANALYSIS FOLLOW-UPS

--------------------------------------------------



Use recent conversation context.



Previous:

"Analyze my Yunara games."



Current:

"What are my biggest positioning problems?"



This may still be personal champion analysis.



Previous:

"Analyze my recent games."



Current:

"What about my farming?"



This may still be personal recent-game analysis.



Do not activate match analysis for unrelated conceptual questions.



==================================================

IMPORTANT CONTEXT RULES

==================================================



- Use recent conversation context.

- Preserve an established player champion when the current follow-up clearly

  refers to it.

- Preserve an established role when appropriate.

- Preserve an established enemy champion when appropriate.

- Never turn a previous enemy champion into player_champion.

- Use only normalized champion names from the champion list.

- If information cannot be inferred, use null.

- Do not automatically preserve knowledge_topics from old questions.

- Select knowledge topics only when relevant to the CURRENT question.



==================================================

QUERY TYPES

==================================================



build:

Builds, items, runes, skill order.



matchup:

One champion versus another.



strategy:

Gameplay, laning, positioning, farming, macro, mechanics, and personal

gameplay analysis.



stats:

Win rate, pick rate, ban rate, rankings, tier strength, meta statistics.



general:

Anything else related to League of Legends.



==================================================

KNOWLEDGE TOPICS

==================================================



Valid knowledge topics:



macro

role_quests

turret_plates

objectives

faelights

bounties



Use the smallest relevant set.



macro:

Rotations, tempo, recalls, waves, side lanes, cross-map trades, grouping,

map pressure, numbers advantages, or general macro decision-making.



role_quests:

Role Quest progression, rewards, restrictions, and strategic effects.



turret_plates:

Turrets, plates, inhibitors, Nexus turrets, Crystalline Overgrowth,

Demolish, structure rewards and structure decisions.



objectives:

Dragons, Dragon Soul, Void Grubs, Herald, Baron, Elder, objective timers,

setup and trades.



faelights:

Faelights, warding, vision gaps, Control Wards and Season 16 vision.



bounties:

Champion and objective bounties, comeback gold and bounty timing.



Do not select knowledge topics merely because player analysis is requested.



==================================================

EXAMPLES

==================================================



"Analyze my games."

→ player_analysis = {{

    "requested": true,

    "mode": "recent_games",

    "champion": null,

    "game_count": null,

    "match_id": null,

    "all_games_requested": false,

    "season_scope": "unspecified",

    "riot_game_name": null,

    "riot_tag_line": null

}}



"Analyze my games, my Riot ID is Cessereendya#7944."

→ player_analysis = {{

    "requested": true,

    "mode": "recent_games",

    "champion": null,

    "game_count": null,

    "match_id": null,

    "all_games_requested": false,

    "season_scope": "unspecified",

    "riot_game_name": "Cessereendya",

    "riot_tag_line": "7944"

}}



"Analyze my last 10 Yunara games, Riot ID Cessereendya#7944."

→ player_champion = "Yunara"

→ player_analysis.mode = "champion_games"

→ player_analysis.champion = "Yunara"

→ player_analysis.game_count = 10

→ player_analysis.riot_game_name = "Cessereendya"

→ player_analysis.riot_tag_line = "7944"



"Analyze all 100 of my Yunara games."

→ player_analysis.game_count = 100

→ player_analysis.all_games_requested = true



"Analyze my Season 15 games."

→ player_analysis.requested = true

→ player_analysis.mode = "recent_games"

→ player_analysis.season_scope = "previous"



"How should I play Yunara?"

→ player_analysis.requested = false



==================================================

CONVERSATION

==================================================



Recent conversation:

{history_text}



Current user message:

{message}

"""
    prompt += """

SPECIFIC GAME SELECTORS (these rules refine the earlier mode examples):
- One particular game is specific_game, even when a champion is named.
- game_count is only a multi-game count; keep it null for specific_game.
- specific_game_index is the 1-based ordinal among games satisfying ALL supplied filters.
- Default specific_game_index to null, not 1. No ordinal means Python must check ambiguity.
- 'most recent', 'recent game', 'latest', 'last game', 'just played' mean index 1.
- 'previous game', 'game before my last game', 'second most recent', '2nd most recent' mean index 2.
- Other explicit ordinals map to their integer, including third/3rd, fourth/4th, etc.
- Preserve invalid explicit indexes for Python validation; do not clamp them.
- kills/deaths/assists are exact K/D/A integers, each null unless supplied.
- In a match request 13/7/11 means KDA, not a date. Keep zeros.
- opponent is the requested opposing lane champion, normalized using CHAMPIONS.
- champion is the champion the user played, normalized using CHAMPIONS.
- Never invent KDA, opponent, ordinal, or match_id, or copy selectors from unrelated earlier games.
- An explicit Match-V5 ID takes priority. Only preserve an ID actually supplied by the user.
- 'previous game' does not mean previous season.

Examples:
'Analyze my 3rd most recent Yunara game.' -> specific_game, champion Yunara, index 3, KDA/opponent null.
'Analyze the Yunara game where I went 13/7/11.' -> specific_game, champion Yunara, index null, KDA 13/7/11.
'Analyze the Yunara game where I went 13/7/11 against Kaisa.' -> same, opponent Kaisa.
'Analyze my most recent Yunara game where I went 13/7/11 against Kaisa.' -> same, index 1.
'Analyze my 2nd most recent Yunara game against Kaisa.' -> specific_game, index 2, champion Yunara,
opponent Kaisa, KDA null.
'Analyze my 2/8/4 Ahri game.' -> specific_game, champion Ahri, KDA 2/8/4, index null.
'Analyze the game where I went 0/3/2.' -> specific_game, champion null, KDA 0/3/2, index null.
'Analyze my last 3 Yunara games.' -> champion_games, game_count 3, specific_game_index null.
'Analyze my last 5 games.' -> recent_games, game_count 5, specific_game_index null.
'Analyze my last game.' -> specific_game, specific_game_index 1, game_count null.
'Analyze my last Yunara game.' -> specific_game, champion Yunara, specific_game_index 1.
'Analyze my Yunara game.' -> specific_game, champion Yunara, specific_game_index null.
'Analyze my previous Yunara game.' -> specific_game, champion Yunara, specific_game_index 2.
Only extract intent; Python will select the actual match. Do not decide which match satisfies these selectors.
"""
    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt,
        config={"max_output_tokens": 2048, "response_mime_type": "application/json", "response_schema": QueryContext},
    )
    context = response.parsed

    if context.player_champion not in CHAMPIONS:
        context.player_champion = None
    if context.enemy_champion not in CHAMPIONS:
        context.enemy_champion = None
    context.requested_champions = [champion for champion in context.requested_champions if champion in CHAMPIONS]

    if context.ranking_count is not None:
        context.ranking_count = min(max(context.ranking_count, 1), 10)
    apply_explicit_game_selector(message, context.player_analysis)
    if context.player_analysis.mode == "specific_game":
        for field in ("champion", "opponent"):
            try:
                setattr(context.player_analysis, field, normalize_selector_champion(getattr(context.player_analysis, field)))
            except SpecificMatchSelectionError:
                # Preserve the invalid selector so app.py can reject it rather than analyze another game.
                pass
    elif context.player_analysis.champion not in CHAMPIONS:
        context.player_analysis.champion = None
    # IMPORTANT:
    # Do not clamp or repair player_analysis.game_count here.
    # app.py must see exactly what the user requested.

    if not context.player_analysis.requested:
        context.player_analysis = PlayerAnalysisRequest()
    return context
