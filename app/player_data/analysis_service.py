"""
Thin Riot retrieval/orchestration layer shared by all three
player-analysis workflows.
"""

import requests

from app.champions import CHAMPIONS
from app.player_data import riot_api
from app.player_data.queue_policy import (
    SUPPORTED_ANALYSIS_QUEUE_IDS, SUPPORTED_ANALYSIS_QUEUES, UnsupportedAnalysisQueueError,
    is_supported_analysis_match, require_supported_analysis_match, queue_search_metadata, skip_unsupported_match,
)
from app.player_data.game_analyser import analyze_game
from app.player_data.match_parser import find_lane_opponent, find_player, parse_match
from app.player_data.player_analyzer import analyze_player, champion_key
from app.player_data.riot_api import RiotRateLimitError
from app.player_data.timeline_parser import parse_timeline


DEFAULT_SCAN_LIMIT = 200
MATCH_BATCH_SIZE = 50

# Product limit:
# analyze at most 20 games per player-analysis request.
MAX_REQUESTED_GAMES = 20

# WaveGuide currently treats Season 16 as the supported season.
CURRENT_SEASON_MAJOR = "16"


def get_match_season_major(match: dict) -> str | None:
    """
    Read the major game version from Riot's match payload.
    """
    # Example:
    # '16.18.702.1234'
    # -> '16'

    game_version = match.get("info", {}).get("gameVersion")

    if not isinstance(game_version, str):
        return None

    game_version = game_version.strip()

    if not game_version:
        return None

    return game_version.split(".", 1)[0]


def is_current_season(match: dict) -> bool:
    """
    Check whether a match belongs to the supported season.
    """
    return get_match_season_major(match) == CURRENT_SEASON_MAJOR


def require_current_season(match: dict) -> None:
    """
    Reject matches with an unknown or unsupported season.
    """
    season_major = get_match_season_major(match)

    if season_major is None:
        raise ValueError("Could not determine the season for this match.")

    if season_major != CURRENT_SEASON_MAJOR:
        raise ValueError("This match is not from the current season.")


def validate_game_count(game_count: int) -> None:
    """
    Validate the requested number of games against the supported limit.
    """
    if not 1 <= game_count <= MAX_REQUESTED_GAMES:
        raise ValueError(f"game_count must be between 1 and " f"{MAX_REQUESTED_GAMES}.")


def analyze_loaded_match(match: dict, puuid: str, routing_region: str) -> dict:
    """
    Analyze an already-fetched Riot match.
    """
    # The match must belong to the current supported season.

    require_current_season(match)
    require_supported_analysis_match(match)

    parsed = parse_match(match, puuid)
    opponent = parsed["opponent"]
    raw_timeline = riot_api.get_match_timeline(parsed["match_id"], routing_region=routing_region)
    timeline = parse_timeline(
        raw_timeline, parsed["player"]["participant_id"], (opponent["participant_id"] if opponent else None)
    )

    return analyze_game(timeline, parsed)


class SpecificMatchSelectionError(ValueError):
    """A selector cannot safely identify one match."""

    def __init__(self, message: str, selection: dict | None = None):
        """
        Keep a user-facing explanation and lightweight search metadata.
        """
        super().__init__(message)
        self.selection = selection or {}


class SpecificMatchNotFoundError(SpecificMatchSelectionError):
    """No game satisfies the requested filters and ordinal."""


class SpecificMatchAmbiguousError(SpecificMatchSelectionError):
    """Multiple games satisfy a selector without an explicit ordinal."""


class SpecificMatchSearchIncompleteError(SpecificMatchSelectionError):
    """Incomplete metadata or search coverage prevents safe selection."""


def normalize_selector_champion(name: str | None) -> str | None:
    """
    Resolve a selector champion to the canonical champion list without dropping invalid filters.
    """
    if name is None:
        return None
    key = "".join(character for character in name.casefold() if character.isalnum())
    for champion in CHAMPIONS:
        if "".join(character for character in champion.casefold() if character.isalnum()) == key:
            return champion
    raise SpecificMatchSelectionError(f"I couldn't recognize the champion '{name}'. Please check the name.")


def validate_specific_selector(specific_game_index=None, kills=None, deaths=None, assists=None) -> None:
    """
    Reject invalid ordinals and incomplete or negative exact KDA selectors.
    """
    if specific_game_index is not None and (type(specific_game_index) is not int or specific_game_index < 1):
        raise SpecificMatchSelectionError("Please specify a game index of at least 1, such as '2nd most recent'.")
    kda = (kills, deaths, assists)
    if any(value is not None for value in kda):
        if not all(type(value) is int and value >= 0 for value in kda):
            raise SpecificMatchSelectionError("Please provide a complete, nonnegative KDA, such as 13/7/11.")


def find_specific_match(puuid: str, routing_region: str = "americas", *, champion: str | None = None,
                        opponent: str | None = None, kills=None, deaths=None, assists=None,
                        specific_game_index: int | None = None,
                        max_matches_scanned: int = DEFAULT_SCAN_LIMIT) -> tuple[dict, dict]:
    """
    Select one current-season match from metadata and return it with lightweight selection details.
    """
    validate_specific_selector(specific_game_index, kills, deaths, assists)
    champion = normalize_selector_champion(champion)
    opponent = normalize_selector_champion(opponent)
    if type(max_matches_scanned) is not int or max_matches_scanned < 1:
        raise SpecificMatchSelectionError("The match search limit must be a positive integer.")

    has_filters = any(value is not None for value in (champion, opponent, kills, deaths, assists))
    # Preserve the old no-selector latest-game fallback, but never apply it to filtered requests.
    index = specific_game_index if specific_game_index is not None or has_filters else 1
    selection = {
        **queue_search_metadata(),
        "method": "ordinal" if index is not None else "filters",
        "matches_scanned": 0, "matching_games_found": 0, "specific_game_index": specific_game_index,
        "effective_game_index": index, "champion": champion, "opponent": opponent,
        "kda": {"kills": kills, "deaths": deaths, "assists": assists},
        "current_season_major": CURRENT_SEASON_MAJOR, "scan_limit": max_matches_scanned,
        "stop_reason": "scan_limit_reached",
    }
    description = "supported current-season" + (f" {champion}" if champion else "") + " games"
    if opponent:
        description += f" against lane opponent {opponent}"
    if kills is not None:
        description += f" where you went {kills}/{deaths}/{assists}"

    seen = set()
    offset = 0
    selected = None
    exhausted = False
    while selection["matches_scanned"] < max_matches_scanned:
        batch_size = min(MATCH_BATCH_SIZE, max_matches_scanned - selection["matches_scanned"])
        ids = riot_api.get_recent_match_ids(puuid, routing_region=routing_region, count=batch_size, start=offset)
        if not ids:
            selection["stop_reason"] = "history_exhausted"
            exhausted = True
            break
        offset += len(ids)
        new_ids = list(dict.fromkeys(match_id for match_id in ids if match_id not in seen))
        if not new_ids:
            selection["stop_reason"] = "no_new_match_ids"
            break

        for match_id in new_ids:
            if selection["matches_scanned"] >= max_matches_scanned:
                break
            seen.add(match_id)
            selection["matches_scanned"] += 1
            # Request failures propagate: skipping candidates could change the ordinal or hide ambiguity.
            match = riot_api.get_match(match_id, routing_region=routing_region)
            season = get_match_season_major(match)
            if season is None:
                selection["stop_reason"] = "unknown_season"
                raise SpecificMatchSearchIncompleteError(
                    "I couldn't verify a candidate game's season, so I couldn't safely select your game.", selection
                )
            if season != CURRENT_SEASON_MAJOR:
                selection["stop_reason"] = "current_season_exhausted"
                exhausted = True
                break

            if skip_unsupported_match(match, selection):
                continue

            player = find_player(match, puuid)
            if champion is not None and player["championName"] != champion:
                continue
            if kills is not None and any(player.get(field) != value for field, value in selection["kda"].items()):
                continue
            if opponent is not None:
                counterpart = find_lane_opponent(match, player)
                if counterpart is None:
                    selection["stop_reason"] = "unknown_lane_opponent"
                    raise SpecificMatchSearchIncompleteError(
                        "A candidate game's lane opponent is unknown, so I couldn't safely apply that filter. "
                        "Please use a match ID or a selector without the opponent.", selection
                    )
                if counterpart["championName"] != opponent:
                    continue

            selection["matching_games_found"] += 1
            selected = match
            if index is not None and selection["matching_games_found"] == index:
                selection["stop_reason"] = "requested_match_found"
                return selected, selection
            if index is None and selection["matching_games_found"] >= 2:
                selection["stop_reason"] = "ambiguity_detected"
                raise SpecificMatchAmbiguousError(
                    f"I found at least 2 {description}. Add another filter or specify which matching game, "
                    "such as 'the most recent one' or 'the second most recent one'.", selection
                )

        if exhausted:
            break
        if len(ids) < batch_size:
            selection["stop_reason"] = "history_exhausted"
            exhausted = True
            break

    if not exhausted:
        raise SpecificMatchSearchIncompleteError(
            f"I checked {selection['matches_scanned']} matches and found {selection['matching_games_found']} "
            f"matching {description}, but the search ended before I could safely select your game. "
            "Please supply a match ID or explicitly request a recent matching game.", selection
        )
    if index is None and selected is not None:
        return selected, selection
    found = selection["matching_games_found"]
    message = (f"I found only {found} {description}, so I couldn't select matching game #{index}."
               if found else f"I couldn't find any {description} matching your request.")
    raise SpecificMatchNotFoundError(message, selection)


def analyze_specific_game(puuid: str, match_id: str | None = None, routing_region: str = "americas", *,
                          champion=None, opponent=None, kills=None, deaths=None, assists=None,
                          specific_game_index=None, max_matches_scanned=DEFAULT_SCAN_LIMIT) -> dict:
    """
    Analyze one current-season game.
    """
    if match_id is not None:
        match = riot_api.get_match(match_id, routing_region=routing_region)
        selection = {**queue_search_metadata(), "method": "match_id", "matches_scanned": 0,
                     "current_season_major": CURRENT_SEASON_MAJOR}
    else:
        match, selection = find_specific_match(
            puuid, routing_region, champion=champion, opponent=opponent, kills=kills, deaths=deaths,
            assists=assists, specific_game_index=specific_game_index, max_matches_scanned=max_matches_scanned
        )
    return {**analyze_loaded_match(match, puuid, routing_region), "selection": selection}


def collect_recent_analyses(puuid: str, game_count: int, champion: str | None, routing_region: str,
                            max_matches_scanned: int) -> tuple[list[dict], dict]:
    """
    Retrieve and analyze recent current-season games.
    """
    # For champion-specific requests this may inspect more matches than
    # game_count because Riot Match-V5 cannot directly filter match IDs
    # by champion.
    #
    # The number of successfully analyzed games can never exceed 20.
    #
    # Riot 429 errors are fatal for the request and propagate immediately.

    validate_game_count(game_count)

    if max_matches_scanned < 1:
        raise ValueError("max_matches_scanned must be positive.")

    if champion is not None and not champion_key(champion):
        raise ValueError("Provide a champion name.")

    queue_metadata = queue_search_metadata()
    analyses = []
    seen = set()
    offset = 0
    scanned = 0
    matching = 0
    failures = []
    stop_reason = "scan_limit_reached"
    current_season_exhausted = False

    while scanned < max_matches_scanned and len(analyses) < game_count:
        batch_size = min(MATCH_BATCH_SIZE, max_matches_scanned - scanned)
        # If this request fails, there is no meaningful way to
        # continue pagination. Let the application handle it.
        ids = riot_api.get_recent_match_ids(puuid, routing_region=routing_region, count=batch_size, start=offset)

        if not ids:
            stop_reason = "history_exhausted"
            break

        offset += len(ids)
        new_ids = [match_id for match_id in ids if match_id not in seen]

        if not new_ids:
            stop_reason = "no_new_match_ids"
            break

        for match_id in new_ids:
            if match_id in seen:
                continue

            seen.add(match_id)

            scanned += 1
            stage = "match"

            try:
                match = riot_api.get_match(match_id, routing_region=routing_region)
                season_major = get_match_season_major(match)

                if season_major is None:
                    failures.append(
                        {"match_id": match_id, "stage": "season", "status": None, "reason": ("missing_game_version")}
                    )

                    continue

                # Match-V5 history is newest-first. Once we have crossed
                # into an older major season, there is no reason to keep
                # scanning farther back.
                if season_major != CURRENT_SEASON_MAJOR:
                    stop_reason = "current_season_exhausted"
                    current_season_exhausted = True

                    break

                if skip_unsupported_match(match, queue_metadata):
                    continue

                parsed = parse_match(match, puuid)

                if champion is not None and champion_key(parsed["player"]["champion"]) != champion_key(champion):
                    continue

                matching += 1
                stage = "timeline"

                analyses.append(analyze_loaded_match(match, puuid, routing_region))

            except RiotRateLimitError:
                # A Riot 429 is not an individual bad-match failure.
                # Stop the whole analysis so app.py can tell the user
                # to retry instead of sending incomplete evidence to Gemini.
                raise

            except requests.HTTPError as error:
                status = error.response.status_code if error.response is not None else None

                # Authentication / API authorization errors affect the
                # entire request, not one isolated match.
                if status in {401, 403}:
                    raise

                failures.append({"match_id": match_id, "stage": stage, "status": status})

                continue

            except requests.RequestException:
                # Network-level failures should not turn into a fake
                # successful player analysis.
                raise

            if len(analyses) == game_count:
                stop_reason = "requested_count_reached"

                break

        if current_season_exhausted:
            break

        if len(analyses) == game_count:
            break

        if len(ids) < batch_size:
            stop_reason = "history_exhausted"

            break

    retrieval = {
        **queue_metadata,
        "requested_games": game_count,
        "games_analyzed": len(analyses),
        "matching_matches_found": matching,
        "matches_scanned": scanned,
        "current_season_major": (CURRENT_SEASON_MAJOR),
        "scan_limit": max_matches_scanned,
        "stop_reason": stop_reason,
        "complete": (len(analyses) == game_count and not failures),
        "failed_matches_may_affect_recency": bool(failures),
        "failures": failures,
    }

    return (analyses, retrieval)


def analyze_recent_games(puuid: str, game_count: int = 20, routing_region: str = "americas",
                         max_matches_scanned: int = DEFAULT_SCAN_LIMIT) -> dict:
    """
    Analyze recent eligible games and aggregate the player report.
    """
    games, retrieval = collect_recent_analyses(
        puuid=puuid,
        game_count=game_count,
        champion=None,
        routing_region=routing_region,
        max_matches_scanned=max_matches_scanned,
    )

    return {**analyze_player(games), "puuid": puuid, "retrieval": retrieval}


def analyze_champion(puuid: str, champion: str, game_count: int = 20, routing_region: str = "americas",
                     max_matches_scanned: int = DEFAULT_SCAN_LIMIT) -> dict:
    """
    Analyze recent eligible games for one champion and aggregate the report.
    """
    games, retrieval = collect_recent_analyses(
        puuid=puuid,
        game_count=game_count,
        champion=champion,
        routing_region=routing_region,
        max_matches_scanned=max_matches_scanned,
    )

    return {**analyze_player(games, champion=champion), "puuid": puuid, "retrieval": retrieval}
