import os
from google import genai
from app.prompts import SYSTEM_PROMPT


client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def ask_gemini(user_message: str, season_knowledge: str, player_data: dict | None, enemy_data: dict | None, player_stats: dict | None,
               matchup_stats: dict | None, requested_stats: dict, role_rankings: dict | None, history: list[dict], role: str | None, query_type: str) -> str:

    conversation = format_history(history)

    prompt = f"""
    {SYSTEM_PROMPT}

    ==============================
    CURRENT SEASON 16 KNOWLEDGE
    ==============================

    The following patch-current knowledge was retrieved because it may be
    relevant to the current question.

    {season_knowledge if season_knowledge else "No additional Season 16 knowledge was retrieved for this question."}

    ==============================
    LIVE STATISTICS
    ==============================

    Player Champion Statistics:
    {player_stats}

    Specific Matchup Statistics:
    {matchup_stats}

    Requested Multi-Champion Statistics:
    {requested_stats}

    Requested Role-wide Rankings:
    {role_rankings}

    ==============================
    CHAMPION DATA
    ==============================

    Player Champion Information:
    {player_data}

    Enemy Champion Information:
    {enemy_data}

    Player Role:
    {role}

    Query Type:
    {query_type}

    ==============================
    CONVERSATION HISTORY
    ==============================

    {conversation}

    ==============================
    CURRENT USER QUESTION
    ==============================

    {user_message}

    ==============================
    CURRENT REQUEST INSTRUCTIONS
    ==============================

    - Answer the current user question directly.

    - Use only the supplied context that is relevant to the current question.
      Do not mention information merely because it appears above.

    - Treat CURRENT SEASON 16 KNOWLEDGE as authoritative for current game
      mechanics. Use QUICK REFERENCE sections for orientation and consult the
      detailed sections when exact values, timings, conditions, exceptions,
      or mechanics are required.

    - When macro.md and a specialized Season 16 knowledge source overlap,
      use the specialized source for exact mechanics and macro.md for
      strategic reasoning.

    - Treat LIVE STATISTICS as authoritative for supplied champion, matchup,
      role, ranking, and meta statistics.

    - If Requested Multi-Champion Statistics contains multiple champions,
      use those entries when comparing their win rate, pick rate, ban rate,
      games, or other supplied statistics.

    - If Requested Role-wide Rankings is provided, answer the ranking from
      those entries. Use the supplied role, metric, ranking order, values,
      and patch when relevant.

    - Use CHAMPION DATA for ability and champion information when relevant
      to practical coaching.

    - Use CONVERSATION HISTORY to resolve follow-up questions and previously
      established context, but prioritize the CURRENT USER QUESTION.

    - Never invent numerical statistics, current mechanics, timings, values,
      or patch-specific information.

    - If an exact current fact required by the question is not available in
      the supplied context, do not fabricate it. Give useful general
      strategic advice when possible and mention the uncertainty only when
      it materially affects the answer.
    """

    response = client.models.generate_content(model="gemini-3.5-flash", contents=prompt)

    return response.text


def format_history(history: list[dict]) -> str:
    result = ""

    for message in history:
        result += f'{message["role"].capitalize()}: {message["content"]}\n'

    return result
