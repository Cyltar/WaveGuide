import json
import os

from google import genai

from app.prompts import SYSTEM_PROMPT


client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def format_json_context(data: dict | None, empty_message: str) -> str:
    """
    Serialize context as JSON or return the empty-context message.
    """
    if data is None:
        return empty_message
    return json.dumps(data, indent=2, ensure_ascii=False)


def ask_gemini(user_message: str, season_knowledge: str, player_data: dict | None, enemy_data: dict | None,
               player_stats: dict | None, matchup_stats: dict | None, requested_stats: dict, role_rankings: dict | None,
               history: list[dict], role: str | None, query_type: str, player_analysis: dict | None = None,
               player_analysis_mode: str | None = None) -> str:
    """
    Generate a coaching response using the supplied conversation and evidence.
    """
    conversation = format_history(history)
    player_analysis_text = format_json_context(
        player_analysis, "No personal player-analysis evidence was supplied for this request."
    )
    prompt = f"""

{SYSTEM_PROMPT}



================================

CURRENT SEASON 16 KNOWLEDGE

================================



The following patch-current knowledge was retrieved because it may be

relevant to the current question.



{season_knowledge if season_knowledge else "No additional Season 16 knowledge was retrieved for this question."}



================================

LIVE STATISTICS

================================



Player Champion Statistics:

{format_json_context(

    player_stats,

    "No player champion statistics were supplied."

)}



Specific Matchup Statistics:

{format_json_context(

    matchup_stats,

    "No specific matchup statistics were supplied."

)}



Requested Multi-Champion Statistics:

{format_json_context(

    requested_stats,

    "No multi-champion statistics were requested."

)}



Requested Role-wide Rankings:

{format_json_context(

    role_rankings,

    "No role-wide ranking data was requested."

)}



================================

CHAMPION DATA

================================



Player Champion Information:

{format_json_context(

    player_data,

    "No player champion data was supplied."

)}



Enemy Champion Information:

{format_json_context(

    enemy_data,

    "No enemy champion data was supplied."

)}



Player Role:

{role}



Query Type:

{query_type}



================================

PLAYER ANALYSIS EVIDENCE

================================



Analysis Mode:

{player_analysis_mode}



Structured Evidence:

{player_analysis_text}



================================

CONVERSATION HISTORY

================================



{conversation if conversation else "No previous conversation history."}



================================

CURRENT USER QUESTION

================================



{user_message}



================================

CURRENT REQUEST INSTRUCTIONS

================================



- Answer the CURRENT USER QUESTION directly.



- Use only supplied context that is relevant to the current question.



- Do not mention information merely because it appears above.



- Treat CURRENT SEASON 16 KNOWLEDGE as authoritative for supplied current

  game mechanics.



- Use QUICK REFERENCE sections for orientation and detailed sections for

  exact mechanics, values, timings, conditions, or exceptions.



- When macro.md and a specialized Season 16 source overlap, use the

  specialized source for exact mechanics and macro.md for strategic reasoning.



- Treat LIVE STATISTICS as authoritative for supplied champion, matchup,

  role, ranking, and meta statistics.



- If Requested Multi-Champion Statistics contains multiple champions,

  use those entries when comparing supplied win rate, pick rate, ban rate,

  games, or other statistics.



- If Requested Role-wide Rankings is provided, use its supplied role,

  metric, ranking order, values, and patch.



- Use CHAMPION DATA for abilities and champion information when relevant.



- Use CONVERSATION HISTORY to resolve follow-ups, but prioritize the current

  question.



- Never invent numerical statistics, current mechanics, timings, values,

  match events, player-history facts, or patch-specific information.



- If an exact current fact required by the question is unavailable, do not

  fabricate it.



- Give useful general strategic advice when possible.



================================

PLAYER ANALYSIS REQUEST RULES

================================



If PLAYER ANALYSIS EVIDENCE is NOT supplied:



- Do not claim to know how this specific user performs in their matches.



- You may still give general League coaching if that answers the question.



If PLAYER ANALYSIS EVIDENCE IS supplied:



- Treat it as the authoritative source for facts and measurements about

  the analyzed games.



- Do not redo arithmetic that the analyzer already calculated.



- Do not infer missing metrics as zero.



- Do not invent replay information.



- Distinguish facts, derived measurements, cautious analyzer inferences,

  and your own coaching interpretation.



- Respect every limitation included in the analysis.



- Respect confidence and evidence-quality fields.



- Use actual sample sizes.



- Do not make stronger claims than the evidence supports.



================================

MODE-SPECIFIC PLAYER ANALYSIS RULES

================================



If Analysis Mode is "specific_game":



- Analyze that game only.



- Do not generalize one game's mistakes into long-term player weaknesses.



- Focus on the most important moments, strengths, mistakes, and improvement

  priorities.



- A death is not automatically a mistake. Review each death independently in this order: surrounding exchange,
  objective follow-up, personal/team trade value, sampled state, recorded damage, then supported interpretation.
- Favorable/even/unfavorable describe observed outcomes, not optimality. Do not turn favorable trades into weaknesses.
- No enemy objective recorded is not proof that the death prevented dragon or saved Soul; check window coverage.
- Do not recommend dodging or using Flash/R/dash/shield/cleanse solely from damage evidence; availability and usability are required.
- Do not invent flank paths, bush positions, rotations, fog-of-war states, or movement sequences from champion identity or death timing.
- Respect unspent_gold_context.suppress_unspent_gold_coaching: do not criticize unspent gold or recommend resetting
  merely to spend after role spending thresholds (TOP/MIDDLE/JUNGLE 20,000; BOTTOM 23,000; UTILITY 12,000).
- Those thresholds do not prove a full inventory. Even below them, high gold does not prove a safe recall opportunity.

- Death recaps must separate recorded events, historical snapshot measurements, unknowns, and interpretation.
- Quote snapshot age with ally distances or health; never describe them as death-time positioning or fight-entry health.
- null proximity means unknown. Empty historical ally lists and multiple attackers do not prove isolation or missing peel.
- Low sampled health and unspent gold do not prove overstay, greed, or a safe recall/escape opportunity.
- Earlier full health does not prove burst from full health; the fight's start and duration may be unknown.
- Grouped ability damage can span multiple recorded hits/casts; it is involvement, not one cast or established cause.
- Ally shields/heals/peel and defensive spell availability are unknown unless directly supported by supplied evidence.
- Champion mechanics never establish that Flash, R, or another escape was available, unused, or could have saved the player.
- cause_candidates and legacy isolation/overstay labels must not become confident explanations or recurring weaknesses.
- Incorporate corrections as user-reported context; do not repeat a conflicting conclusion from an earlier snapshot.
- State when evidence is insufficient instead of inventing a "Why you died" explanation.
- If no supported weakness is established, say so; do not invent one to fill a response heading.

- When discussing deaths, use the supplied death evidence rather than only

  KDA or killer identity.



- Team events after the player's death are context, not proof that the death

  caused the outcome.



If Analysis Mode is "recent_games":



- Focus primarily on recurring patterns across distinct games.



- Use role/queue cohorts when the report separates them.



- Do not blindly pool incompatible roles or queues.



- Distinguish recurring patterns from limited observations.



- Use concrete pattern examples when useful, but remember those examples are

  supporting evidence rather than a representative sample.



If Analysis Mode is "champion_games":



- Keep the conclusions specific to the requested champion.



- Use the champion-specific sample size.



- Do not automatically generalize champion-specific weaknesses to every

  champion or role the user plays.



- Use recurring ability/death patterns when they materially explain how enemy

  threats affect the player's deaths.



================================

MULTI-GAME SAMPLE RULES

================================



If a multi-game report contains retrieval metadata:



- Check `requested_games`.



- Check `games_analyzed`.



- Check `complete`.



- Check `stop_reason`.



If fewer games were analyzed than requested, base the report on the actual

number analyzed.



When materially relevant, tell the user the real sample size.



Do not pretend an incomplete sample is complete.



If the report separates data into cohorts:



- do not sum overlapping top-level and cohort counts



- do not manufacture a combined average when the analyzer intentionally

  withheld one



- interpret the relevant cohort instead



================================

DEATH ABILITY RULES

================================



If `death_ability_patterns` are supplied:



- Treat them as recorded enemy ability-damage involvement.



- You may use League knowledge to explain the normal function of a known

  ability.



- Do NOT assume the ability initiated the fight.



- Do NOT assume the ability caused the player's mistake.



- Do NOT treat every damaging ability as equally important.



- Distinguish ordinary damage abilities from genuine engage/CC threats using

  League knowledge.



- Missing ability evidence does not mean no important ability or engage

  occurred.



================================

FINAL ANSWER PRIORITIES

================================



For a player-analysis response, prioritize:



1. the strongest overall takeaway

2. the most reliable recurring strengths

3. the most important weaknesses

4. concrete supporting evidence

5. practical improvement priorities



Do not dump every available metric.



Do not dump raw analysis JSON.



Turn the strongest evidence into useful coaching.

"""
    response = client.models.generate_content(model="gemini-3.5-flash", contents=prompt)

    return response.text


def format_history(history: list[dict]) -> str:
    """
    Format prior chat messages for the model prompt.
    """
    result = ""

    for message in history:
        result += f'{message["role"].capitalize()}: ' f'{message["content"]}\n'
    return result
