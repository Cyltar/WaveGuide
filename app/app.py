import os
import re
import time

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from app.auth import AuthenticatedUser, get_current_user
from app.database import *
from app.guest_trial import GuestRun
from app.guest_gateway import mount_guest
from app.errors import handle_external_error
from app.gemini import ask_gemini
from app.knowledge.knowledge_loader import load_relevant_knowledge
from app.player_data.analysis_service import *
from app.player_data.riot_api import RiotRateLimitError
from app.query_parser import parse_query
from app.stats import get_role_rankings
from app.supabase_client import create_user_client, supabase as account_admin


app = FastAPI(title="WaveGuide", version="1.0")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", os.environ.get("FRONTEND_URL", "")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


DEFAULT_PLAYER_ANALYSIS_GAMES = 20

ALLOWED_RIOT_ROUTING_REGIONS = {"americas", "europe", "asia", "sea"}


# =========================================================
# Riot ID Parsing
# =========================================================

# Handles:
# "my Riot ID is Cessereendya#7944"
# "Riot ID: My Name#NA1"
#
# A labelled Riot ID may contain spaces in the game name.

LABELLED_RIOT_ID_PATTERN = re.compile(
    r"\briot\s*id\s*(?:is|:|=)?\s*" r"([^#\r\n]{1,100}?)\s*#\s*" r"([A-Za-z0-9]{1,30})\b", re.IGNORECASE
)

# Handles simple IDs appearing by themselves:
# "Cessereendya#7944"
#
# This intentionally uses a stricter game-name shape to avoid
# accidentally capturing an entire normal sentence before '#'.

GENERIC_RIOT_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])" r"([A-Za-z0-9][A-Za-z0-9_.-]{0,99})" r"#([A-Za-z0-9]{1,30})\b"
)


# =========================================================
# Pydantic Models
# =========================================================


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    session_id: str


class RiotAccountRequest(BaseModel):
    game_name: str = Field(min_length=1, max_length=100)
    tag_line: str = Field(min_length=1, max_length=30)
    routing_region: str = "americas"


# =========================================================
# Chat Storage Helpers
# =========================================================


def save_and_return_chat_response(user_client, user_id: str, session_id: str | None, user_message: str, answer: str,
                                  latency_ms: int, used_context: dict | None = None) -> ChatResponse:
    """
    Save the conversation messages and return the chat response.
    """
    if isinstance(user_client, GuestRun):
        user_client.context = used_context
        return ChatResponse(answer=answer, session_id=user_client.conversation, **(
            {"structured": used_context["structured"]} if used_context and used_context.get("structured") else {}))
    if session_id is None:
        session_id = create_chat_session(client=user_client, user_id=user_id, title=user_message[:50])
    save_chat_message(client=user_client, session_id=session_id, role="user", content=user_message)

    save_chat_message(
        client=user_client,
        session_id=session_id,
        role="assistant",
        content=answer,
        used_context=used_context,
        latency_ms=latency_ms,
    )

    return ChatResponse(answer=answer, session_id=session_id)


# =========================================================
# Riot ID Session Helpers
# =========================================================


def extract_riot_id_from_text(text: str) -> tuple[str, str] | None:
    """
    Extract a Riot ID from a chat message.
    """
    # This is a deterministic fallback. The query parser still performs
    # the primary semantic extraction.

    labelled_match = LABELLED_RIOT_ID_PATTERN.search(text)

    if labelled_match is not None:
        game_name = labelled_match.group(1).strip()
        tag_line = labelled_match.group(2).strip()

        if game_name and tag_line:
            return (game_name, tag_line)
    generic_match = GENERIC_RIOT_ID_PATTERN.search(text)

    if generic_match is None:
        return None
    game_name = generic_match.group(1).strip()
    tag_line = generic_match.group(2).strip()

    if not game_name or not tag_line:
        return None
    return (game_name, tag_line)


def get_recent_riot_id_from_history(history: list[dict]) -> tuple[str, str] | None:
    """
    Find the most recently supplied Riot ID in this chat only.
    """
    # Search from newest to oldest and only inspect user messages.

    for message in reversed(history):
        if message.get("role") != "user":
            continue
        content = message.get("content")

        if not isinstance(content, str):
            continue
        riot_id = extract_riot_id_from_text(content)

        if riot_id is not None:
            return riot_id
    return None


# =========================================================
# Player Analysis Scope
# =========================================================


def get_player_analysis_scope_message(context) -> str | None:
    """
    Return a message for unsupported analysis scope or game counts.
    """
    request = context.player_analysis

    if not request.requested:
        return None
    if request.mode == "specific_game" and request.match_id is None:
        try:
            validate_specific_selector(request.specific_game_index, request.kills, request.deaths, request.assists)
            normalize_selector_champion(request.champion)
            normalize_selector_champion(request.opponent)
        except SpecificMatchSelectionError as error:
            return str(error)
    if request.season_scope in {"previous", "all"}:
        return (
            "WaveGuide's player analysis currently supports only "
            f"the current League season (Season {CURRENT_SEASON_MAJOR}). "
            f"I can analyze up to {MAX_REQUESTED_GAMES} of your "
            "current-season games instead."
        )
    if request.game_count is not None and request.game_count < 1:
        return "Please request at least one game " "for player analysis."
    if request.game_count is not None and request.game_count > MAX_REQUESTED_GAMES:
        if request.champion:
            return (
                "WaveGuide can analyze at most "
                f"{MAX_REQUESTED_GAMES} "
                f"{request.champion} games at a time, "
                "all from the current season. "
                f"You requested {request.game_count}. "
                f"I can analyze your {MAX_REQUESTED_GAMES} most "
                f"recent current-season {request.champion} games instead."
            )
        return (
            "WaveGuide can analyze at most "
            f"{MAX_REQUESTED_GAMES} games at a time, "
            "all from the current season. "
            f"You requested {request.game_count}. "
            f"I can analyze your {MAX_REQUESTED_GAMES} most recent "
            "current-season games instead."
        )
    if request.all_games_requested:
        if request.champion:
            return (
                "WaveGuide does not analyze an unlimited match history. "
                f"I can analyze up to {MAX_REQUESTED_GAMES} of your "
                f"most recent current-season {request.champion} games."
            )
        return (
            "WaveGuide does not analyze an unlimited match history. "
            f"I can analyze up to {MAX_REQUESTED_GAMES} of your "
            "most recent current-season games."
        )
    return None


def get_player_analysis_error_message(error: ValueError) -> str | None:
    """
    Translate analysis validation errors into user-facing messages.
    """
    message = str(error)
    if isinstance(error, (SpecificMatchSelectionError, UnsupportedAnalysisQueueError)):
        return message
    lowered = message.lower()

    if "current season" in lowered or "determine the season" in lowered:
        return (
            "WaveGuide can only analyze matches from " f"the current League season " f"(Season {CURRENT_SEASON_MAJOR})."
        )
    if "no recent matches available" in lowered:
        return "I couldn't find a recent current-season " "match for that Riot account."
    if "player not found in match" in lowered:
        return "That match does not appear to belong to " "the Riot account being analyzed."
    if "provide a champion name" in lowered:
        return "Tell me which champion you want me to analyze."
    if "game_count" in lowered:
        return "WaveGuide can analyze between 1 and " f"{MAX_REQUESTED_GAMES} games at a time."
    return None


def get_riot_rate_limit_message(error: RiotRateLimitError) -> str:
    """
    Explain the Riot rate limit and any retry delay.
    """
    if error.retry_after is not None:
        return (
            "Riot is temporarily rate-limiting match requests, "
            "so I couldn't complete your player analysis. "
            f"Please try again in about {error.retry_after} seconds."
        )
    return (
        "Riot is temporarily rate-limiting match requests, "
        "so I couldn't complete your player analysis. "
        "Please try again shortly."
    )


# =========================================================
# Player Account Resolution
# =========================================================


def resolve_explicit_riot_account(context, history: list[dict]) -> dict | None:
    """
    Resolve an unlinked Riot account for this request.
    """
    # Priority here:
    # 1. Riot ID from the parsed current request
    # 2. Most recent Riot ID from this chat session
    #
    # This never writes to riot_accounts.

    request = context.player_analysis
    game_name = request.riot_game_name
    tag_line = request.riot_tag_line
    account_source = "message"

    if game_name is None or tag_line is None:
        previous_riot_id = get_recent_riot_id_from_history(history)

        if previous_riot_id is None:
            return None
        (game_name, tag_line) = previous_riot_id
        account_source = "session_history"
    try:
        account = riot_api.get_account_by_riot_id(game_name=game_name, tag_line=tag_line, routing_region="americas")
    except RiotRateLimitError:
        raise
    except requests.HTTPError as error:
        if error.response is not None and error.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": ("RIOT_ACCOUNT_NOT_FOUND"),
                    "message": ("I couldn't find the Riot ID " f"{game_name}#{tag_line}."),
                },
            )
        raise
    return {
        "riot_game_name": (account["gameName"]),
        "riot_tag_line": (account["tagLine"]),
        "riot_puuid": (account["puuid"]),
        "routing_region": ("americas"),
        "source": account_source,
    }


def resolve_player_riot_account(context, user_client, user_id: str, history: list[dict]) -> dict | None:
    """
    Determine which Riot account should be analyzed.
    """
    # Priority:
    # 1. Riot ID in current request
    # 2. Riot ID from current chat history
    # 3. Permanently linked Riot account

    temporary_account = resolve_explicit_riot_account(context=context, history=history)

    if temporary_account is not None:
        return temporary_account
    if isinstance(user_client, GuestRun):
        return None
    linked_account = get_riot_account(user_client, user_id)

    if linked_account is None:
        return None
    return {**linked_account, "source": "linked"}


# =========================================================
# Player Analysis Execution
# =========================================================


def run_player_analysis(context, riot_account: dict) -> dict:
    """
    Dispatch the requested analysis for the resolved Riot account.
    """
    request = context.player_analysis
    puuid = riot_account["riot_puuid"]
    routing_region = riot_account.get("routing_region") or "americas"

    if request.mode == "specific_game":
        return analyze_specific_game(
            puuid=puuid, match_id=request.match_id, routing_region=routing_region,
            champion=request.champion, opponent=request.opponent, kills=request.kills,
            deaths=request.deaths, assists=request.assists, specific_game_index=request.specific_game_index
        )
    if request.mode == "recent_games":
        game_count = request.game_count if request.game_count is not None else DEFAULT_PLAYER_ANALYSIS_GAMES

        return analyze_recent_games(puuid=puuid, game_count=game_count, routing_region=routing_region)
    if request.mode == "champion_games":
        champion = request.champion or context.player_champion

        if champion is None:
            raise ValueError("Provide a champion name.")
        game_count = request.game_count if request.game_count is not None else DEFAULT_PLAYER_ANALYSIS_GAMES

        return analyze_champion(puuid=puuid, champion=champion, game_count=game_count, routing_region=routing_region)
    raise ValueError("Unsupported player analysis mode.")


def sanitize_player_analysis(value):
    """
    Strip private account identifiers before sending deterministic analysis evidence to Gemini.
    """

    private_keys = {"puuid", "riot_id", "user_id"}

    if isinstance(value, dict):
        return {key: sanitize_player_analysis(item) for key, item in value.items() if key not in private_keys}
    if isinstance(value, list):
        return [sanitize_player_analysis(item) for item in value]
    return value


def summarize_player_analysis_context(analysis: dict | None, mode: str | None,
                                      account_source: str | None = None) -> dict | None:
    """
    Summarize analysis metadata for stored chat context.
    """
    if analysis is None:
        return None
    summary = {
        "mode": mode,
        "account_source": (account_source),
        "analysis_version": (analysis.get("analysis_version")),
        "schema_version": (analysis.get("schema_version")),
    }

    if analysis.get("match_id"):
        summary["match_id"] = analysis["match_id"]
    if analysis.get("games_analyzed") is not None:
        summary["games_analyzed"] = analysis["games_analyzed"]
    if analysis.get("champion_filter"):
        summary["champion_filter"] = analysis["champion_filter"]
    retrieval = analysis.get("retrieval")

    if retrieval:
        summary["retrieval"] = {
            "requested_games": (retrieval.get("requested_games")),
            "games_analyzed": (retrieval.get("games_analyzed")),
            "complete": (retrieval.get("complete")),
            "stop_reason": (retrieval.get("stop_reason")),
        }
    return summary


def multi_game_analysis_has_no_games(context, player_analysis: dict) -> bool:
    """
    Guard against sending a zero-game multi-game report to Gemini.
    """

    if context.player_analysis.mode not in {"recent_games", "champion_games"}:
        return False
    return player_analysis.get("games_analyzed", 0) == 0


# =========================================================
# Chat Endpoint
# =========================================================


def chat(request: ChatRequest, auth: AuthenticatedUser = Depends(get_current_user)):
    """
    Answer a chat request using the relevant context and save the conversation.
    """
    start_time = time.perf_counter()

    try:
        if isinstance(auth, GuestRun):
            user_id = user_client = auth
            session_id, history = auth.conversation, auth.history
        else:
            user_id = auth.user_id

            check_daily_ai_request_limit(user_id)

            user_client = create_user_client(auth.access_token)
            session_id = request.session_id

            if session_id is not None:
                if not user_owns_session(user_client, session_id):
                    raise HTTPException(status_code=404, detail=("Conversation not found."))
                history = get_chat_history(user_client, session_id)
            else:
                history = []
        # -------------------------------------------------
        # Query parsing
        # -------------------------------------------------

        context = parse_query(message=request.message, recent_history=history)
        # -------------------------------------------------
        # Validate player-analysis scope BEFORE Match-V5.
        # -------------------------------------------------
        scope_message = get_player_analysis_scope_message(context)

        if scope_message is not None:
            latency_ms = int((time.perf_counter() - start_time) * 1000)

            return save_and_return_chat_response(
                user_client=user_client,
                user_id=user_id,
                session_id=session_id,
                user_message=request.message,
                answer=scope_message,
                latency_ms=latency_ms,
                used_context={"player_analysis_rejected": True, "reason": ("unsupported_scope")},
            )
        # -------------------------------------------------
        # Player analysis
        # -------------------------------------------------

        player_analysis = None
        riot_account = None

        if context.player_analysis.requested:
            try:
                riot_account = resolve_player_riot_account(
                    context=context, user_client=user_client, user_id=user_id, history=history
                )

                if riot_account is None:
                    answer = (
                        "To analyze your games, either link your Riot "
                        "account to WaveGuide or include your Riot ID "
                        "in the message, for example: "
                        "`Analyze my games, my Riot ID is "
                        "Cessereendya#7944`."
                    )
                    latency_ms = int((time.perf_counter() - start_time) * 1000)

                    return save_and_return_chat_response(
                        user_client=user_client,
                        user_id=user_id,
                        session_id=session_id,
                        user_message=request.message,
                        answer=answer,
                        latency_ms=latency_ms,
                        used_context={"player_analysis_requested": True, "riot_account_available": False},
                    )
                player_analysis = run_player_analysis(context, riot_account)

                # Never ask Gemini to "analyze" a multi-game report
                # that contains no successfully analyzed games.

                if multi_game_analysis_has_no_games(context, player_analysis):
                    retrieval = player_analysis.get("retrieval", {})

                    if context.player_analysis.champion:
                        target_description = context.player_analysis.champion + " games"
                    else:
                        target_description = "games"
                    answer = (
                        f"I couldn't find any supported current-season {target_description} to analyze "
                        "within the available search. WaveGuide supports Draft, Ranked Solo/Duo, "
                        "Ranked Flex, and Swiftplay on Summoner's Rift."
                    )
                    latency_ms = int((time.perf_counter() - start_time) * 1000)

                    return save_and_return_chat_response(
                        user_client=user_client,
                        user_id=user_id,
                        session_id=session_id,
                        user_message=request.message,
                        answer=answer,
                        latency_ms=latency_ms,
                        used_context={"player_analysis_requested": True, "games_analyzed": 0, "retrieval": retrieval},
                    )
            except RiotRateLimitError as error:
                answer = get_riot_rate_limit_message(error)
                latency_ms = int((time.perf_counter() - start_time) * 1000)

                return save_and_return_chat_response(
                    user_client=user_client,
                    user_id=user_id,
                    session_id=session_id,
                    user_message=request.message,
                    answer=answer,
                    latency_ms=latency_ms,
                    used_context={
                        "player_analysis_requested": True,
                        "riot_rate_limited": True,
                        "retry_after": (error.retry_after),
                    },
                )
            except ValueError as error:
                answer = get_player_analysis_error_message(error)

                if answer is None:
                    raise
                latency_ms = int((time.perf_counter() - start_time) * 1000)

                return save_and_return_chat_response(
                    user_client=user_client,
                    user_id=user_id,
                    session_id=session_id,
                    user_message=request.message,
                    answer=answer,
                    latency_ms=latency_ms,
                    used_context={"player_analysis_requested": True, "player_analysis_error": (str(error))},
                )
        # -------------------------------------------------
        # Season knowledge
        # -------------------------------------------------

        season_knowledge = load_relevant_knowledge(context.knowledge_topics)
        # -------------------------------------------------
        # Champion/stat context
        # -------------------------------------------------
        player_data = None
        enemy_data = None
        player_stats = None
        matchup_stats = None
        requested_stats = {}
        role_rankings = None
        effective_player_champion = context.player_champion

        # For specific-game analysis the parser might not know
        # which champion the user played. The deterministic match
        # analysis does.

        if (
            effective_player_champion is None
            and player_analysis is not None
            and context.player_analysis.mode == "specific_game"
        ):
            effective_player_champion = player_analysis.get("player", {}).get("champion")
        if context.requested_champions and context.role is not None:
            for champion in context.requested_champions:
                requested_stats[champion] = get_stats(champion, context.role)
        if context.ranking_metric is not None and context.role is not None:
            ranking_count = context.ranking_count or 5
            role_rankings = get_role_rankings(context.role, context.ranking_metric, ranking_count)
        if effective_player_champion is not None:
            player_data = get_champion(effective_player_champion)
        if context.enemy_champion is not None:
            enemy_data = get_champion(context.enemy_champion)
        if effective_player_champion is not None and context.role is not None:
            player_stats = get_stats(effective_player_champion, context.role)
            matchup_stats = get_specific_matchup(player_stats, context.enemy_champion)
        # -------------------------------------------------
        # Sanitize deterministic player evidence
        # -------------------------------------------------

        gemini_player_analysis = sanitize_player_analysis(player_analysis) if player_analysis is not None else None
        # -------------------------------------------------
        # Final Gemini response
        # -------------------------------------------------
        answer = ask_gemini(
            user_message=request.message,
            season_knowledge=season_knowledge,
            player_data=player_data,
            enemy_data=enemy_data,
            player_stats=player_stats,
            matchup_stats=matchup_stats,
            requested_stats=requested_stats,
            role_rankings=role_rankings,
            history=history,
            role=context.role,
            query_type=context.query_type,
            player_analysis=gemini_player_analysis,
            player_analysis_mode=(context.player_analysis.mode if (context.player_analysis.requested) else None),
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        # Only successful final AI responses count against
        # WaveGuide's daily AI request limit.

        record_successful_ai_request(user_id)

        used_context = {
            "player_champion": (effective_player_champion),
            "enemy_champion": (context.enemy_champion),
            "requested_champions": (context.requested_champions),
            "role": (context.role),
            "query_type": (context.query_type),
            "matchup_stats": (matchup_stats),
            "knowledge_topics": (context.knowledge_topics),
            "role_rankings": (role_rankings),
            "player_analysis": (
                summarize_player_analysis_context(
                    analysis=player_analysis,
                    mode=(context.player_analysis.mode),
                    account_source=(riot_account.get("source") if riot_account else None),
                )
            ),
        }

        return save_and_return_chat_response(
            user_client=user_client,
            user_id=user_id,
            session_id=session_id,
            user_message=request.message,
            answer=answer,
            latency_ms=latency_ms,
            used_context=used_context,
        )
    except HTTPException:
        raise
    except Exception as error:
        handle_external_error(error)


# =========================================================
# Riot Account Endpoints
# =========================================================


@app.post("/riot-account")
def link_riot_account(request: RiotAccountRequest, auth: AuthenticatedUser = Depends(get_current_user)):
    """
    Resolve and save the authenticated user's Riot account.
    """
    try:
        routing_region = request.routing_region.strip().lower()

        if routing_region not in ALLOWED_RIOT_ROUTING_REGIONS:
            raise HTTPException(
                status_code=400,
                detail={"code": ("INVALID_RIOT_REGION"), "message": ("Unsupported Riot routing region.")},
            )
        game_name = request.game_name.strip()
        tag_line = request.tag_line.strip()

        try:
            account = riot_api.get_account_by_riot_id(
                game_name=game_name, tag_line=tag_line, routing_region=routing_region
            )
        except RiotRateLimitError as error:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": ("RIOT_RATE_LIMITED"),
                    "message": (get_riot_rate_limit_message(error)),
                    "retry_after": (error.retry_after),
                },
            )
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail={"code": ("RIOT_ACCOUNT_NOT_FOUND"), "message": ("That Riot ID could not be found.")},
                )
            raise
        user_client = create_user_client(auth.access_token)
        saved = save_riot_account(
            client=user_client,
            user_id=auth.user_id,
            game_name=(account["gameName"]),
            tag_line=(account["tagLine"]),
            puuid=(account["puuid"]),
            routing_region=(routing_region),
        )

        return {
            "linked": True,
            "riot_id": (f'{saved["riot_game_name"]}' f'#{saved["riot_tag_line"]}'),
            "routing_region": (saved["routing_region"]),
        }
    except HTTPException:
        raise
    except Exception as error:
        handle_external_error(error)


@app.get("/riot-account")
def get_linked_riot_account(auth: AuthenticatedUser = Depends(get_current_user)):
    """
    Return the authenticated user's linked Riot account status.
    """
    user_client = create_user_client(auth.access_token)
    account = get_riot_account(user_client, auth.user_id)

    if account is None:
        return {"linked": False}
    return {
        "linked": True,
        "riot_id": (f'{account["riot_game_name"]}' f'#{account["riot_tag_line"]}'),
        "routing_region": (account["routing_region"]),
    }


@app.delete("/riot-account")
def unlink_riot_account(auth: AuthenticatedUser = Depends(get_current_user)):
    """
    Remove the authenticated user's linked Riot account.
    """
    user_client = create_user_client(auth.access_token)

    delete_riot_account(user_client, auth.user_id)

    return {"linked": False}


# =========================================================
# Existing Endpoints
# =========================================================


@app.get("/champions")
def get_champions():
    """
    Return the supported champion names.
    """
    return {"champions": CHAMPIONS}


@app.get("/sessions/{session_id}")
def get_session(session_id: str, auth: AuthenticatedUser = Depends(get_current_user)):
    """
    Return messages from a session owned by the authenticated user.
    """
    user_client = create_user_client(auth.access_token)

    if not user_owns_session(user_client, session_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    messages = get_session_messages(user_client, session_id)

    return {"messages": messages}


@app.get("/sessions")
def get_sessions(auth: AuthenticatedUser = Depends(get_current_user)):
    """
    List the authenticated user's chat sessions.
    """
    user_client = create_user_client(auth.access_token)

    return {"sessions": (get_user_sessions(user_client))}


@app.delete("/account")
def delete_account(auth: AuthenticatedUser = Depends(get_current_user)):
    """
    Permanently delete the authenticated account and its cascading user-owned records.
    """
    try:
        # User-owned foreign keys cascade from auth.users; never delete shared caches manually.
        account_admin.auth.admin.delete_user(auth.user_id, should_soft_delete=False)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail={"code": "ACCOUNT_DELETION_FAILED", "message": "Unable to delete your account. Please try again."},
        ) from None
    return {"deleted": True}


mount_guest(app, get_current_user, chat, ChatRequest)
