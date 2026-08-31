import os
from google import genai
from app.prompts import SYSTEM_PROMPT


client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def ask_gemini(user_message: str, player_data: dict | None, enemy_data: dict | None, player_stats: dict | None, matchup_stats: dict | None, requested_stats: dict, role_rankings: dict | None, history: list[dict], role: str | None, query_type: str) -> str:
    conversation = format_history(history)

    prompt = f"""
    {SYSTEM_PROMPT}

    Player Champion Information:
    {player_data}

    Enemy Champion Information:
    {enemy_data}

    Player Role:
    {role}

    Query Type:
    {query_type}

    Player Champion Statistics:
    {player_stats}

    Specific Matchup Statistics:
    {matchup_stats}

    Requested Multi-Champion Statistics:
    {requested_stats}

    Requested Role-wide Rankings:
    {role_rankings}

    Conversation History:
    {conversation}

    Current User Question:
    {user_message}

    DATA INSTRUCTIONS

    - Treat the provided statistics as the source of truth.
    - Never invent numerical League statistics.
    - If Requested Multi-Champion Statistics contains several champions,
      use those statistics when comparing them or answering questions such
      as win rate, pick rate, ban rate, or meta performance.
    - If Requested Role-wide Rankings is provided, answer the ranking directly
      from its entries and mention its role, metric, and patch when available.
    - Do not claim statistics are unavailable if relevant data exists above.
    - If statistics genuinely are not provided, answer without inventing them.
    - Use champion ability information when relevant for practical coaching.
    """

    response = client.models.generate_content(model="gemini-3.5-flash", contents=prompt)

    return response.text


def format_history(history: list[dict]) -> str:
    result = ""

    for message in history:
        result += f'{message["role"].capitalize()}: {message["content"]}\n'

    return result
