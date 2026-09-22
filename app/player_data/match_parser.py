def find_player(match: dict, puuid: str) -> dict:
    """
    Find the match participant with the requested player identifier.
    """
    participants = match["info"]["participants"]

    for participant in participants:
        if participant["puuid"] == puuid:
            return participant
    raise ValueError("Player not found in match.")


def find_lane_opponent(match: dict, player: dict) -> dict | None:
    """
    Find the opposing participant with the player's known role.
    """
    participants = match["info"]["participants"]
    player_team_id = player["teamId"]
    player_role = player.get("teamPosition")
    if player_role not in {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}:
        return None
    opponents = [
        participant
        for participant in participants
        if participant["teamId"] != player_team_id and participant.get("teamPosition") == player_role
    ]
    return opponents[0] if len(opponents) == 1 else None


def extract_player_stats(player: dict) -> dict:
    """
    Extract summary statistics for one match participant.
    """
    cs = player["totalMinionsKilled"] + player["neutralMinionsKilled"]

    return {
        "participant_id": player["participantId"],
        "puuid": player["puuid"],
        "riot_id": f'{player.get("riotIdGameName", "")}#{player.get("riotIdTagline", "")}',
        "champion": player["championName"],
        "role": player.get("teamPosition") or "UNKNOWN",
        "win": player["win"],
        "kills": player["kills"],
        "deaths": player["deaths"],
        "assists": player["assists"],
        "cs": cs,
        "lane_cs": player["totalMinionsKilled"],
        "jungle_cs": player["neutralMinionsKilled"],
        "gold": player["goldEarned"],
        "level": player["champLevel"],
    }


def parse_match(match: dict, puuid: str) -> dict:
    """
    Extract player, opponent, and team context from a match summary.
    """
    player = find_player(match, puuid)
    opponent = find_lane_opponent(match, player)
    participant_teams = {}
    participant_info = {}

    for participant in match["info"]["participants"]:
        participant_id = participant["participantId"]
        participant_teams[participant_id] = participant["teamId"]
        participant_info[participant_id] = {
            "team_id": participant["teamId"],
            "champion": participant["championName"],
            "role": participant.get("teamPosition") or "UNKNOWN",
            "riot_id": (f'{participant.get("riotIdGameName", "")}' f'#{participant.get("riotIdTagline", "")}'),
        }
    parsed_match = {
        "match_id": match["metadata"]["matchId"],
        "game_duration": match["info"]["gameDuration"],
        "game_start_timestamp": match["info"].get("gameStartTimestamp", match["info"].get("gameCreation")),
        "game_version": match["info"]["gameVersion"],
        "queue_id": match["info"]["queueId"],
        "map_id": match["info"].get("mapId"),
        "player": extract_player_stats(player),
        "opponent": None,
        "participant_teams": participant_teams,
        "participant_info": participant_info,
    }

    if opponent is not None:
        parsed_match["opponent"] = extract_player_stats(opponent)
    return parsed_match


if __name__ == "__main__":
    from app.player_data.riot_api import get_account_by_riot_id, get_recent_match_ids, get_match

    account = get_account_by_riot_id(game_name="Cessereendya", tag_line="7944")
    puuid = account["puuid"]
    match_ids = get_recent_match_ids(puuid=puuid, count=1)
    match = get_match(match_ids[0])
    parsed = parse_match(match=match, puuid=puuid)

    print(parsed)
