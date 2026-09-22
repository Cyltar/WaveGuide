from app.player_data.match_parser import parse_match


PLAYER_EVENT_TYPES = {"LEVEL_UP", "ITEM_PURCHASED", "ITEM_SOLD", "ITEM_UNDO"}

GLOBAL_EVENT_TYPES = {
    "WARD_PLACED",
    "WARD_KILL",
    "CHAMPION_KILL",
    "TURRET_PLATE_DESTROYED",
    "BUILDING_KILL",
    "ELITE_MONSTER_KILL",
    "OBJECTIVE_BOUNTY_PRESTART",
    "OBJECTIVE_BOUNTY_FINISH",
    "DRAGON_SOUL_GIVEN",
    "GAME_END",
}


def format_timestamp(timestamp: int) -> str:
    """
    Format a millisecond timestamp as minutes and seconds.
    """
    total_seconds = timestamp // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60

    return f"{minutes}:{seconds:02}"


def parse_position(position: dict | None) -> dict | None:
    """
    Extract map coordinates when a position is available.
    """
    if position is None:
        return None
    return {"x": position["x"], "y": position["y"]}


def parse_participant_frame(frame: dict, participant_id: int) -> dict:
    """
    Extract a requested participant's sampled timeline state.
    """
    participant_frames = frame["participantFrames"]
    participant = participant_frames.get(str(participant_id))

    if participant is None:
        raise ValueError(f"Participant {participant_id} not found in timeline frame.")
    return parse_light_participant_frame({**participant, "participantId": participant_id})


def parse_light_participant_frame(participant: dict) -> dict:
    """
    Extract compact participant state while preserving unknown health.
    """
    champion_stats = participant.get("championStats", {})
    health = champion_stats.get("health")
    max_health = champion_stats.get("healthMax")
    alive = None

    if health is not None:
        alive = health > 0
    lane_cs = participant.get("minionsKilled", 0)
    jungle_cs = participant.get("jungleMinionsKilled", 0)

    return {
        "participant_id": participant["participantId"],
        "total_gold": participant.get("totalGold", 0),
        "current_gold": participant.get("currentGold", 0),
        "level": participant.get("level", 0),
        "xp": participant.get("xp", 0),
        "lane_cs": lane_cs,
        "jungle_cs": jungle_cs,
        "total_cs": lane_cs + jungle_cs,
        "health": health,
        "max_health": max_health,
        "alive": alive,
        "position": parse_position(participant.get("position")),
    }


def parse_all_participants(frame: dict) -> dict[int, dict]:
    """
    Parse sampled state for every participant in a frame.
    """
    participants = {}

    for participant_id, participant in frame["participantFrames"].items():
        participants[int(participant_id)] = parse_light_participant_frame(participant)
    return participants


def parse_damage_sources(event: dict) -> list[dict]:
    """
    Group reported damage records while retaining source identity fields.
    """
    grouped = {}

    for hit in event.get("victimDamageReceived", []):
        participant_id = hit.get("participantId")
        spell_name = hit.get("spellName") or ""
        basic = hit.get("basic", False)
        key = (participant_id, spell_name, basic, hit.get("name"), hit.get("spellSlot"))

        if key not in grouped:
            grouped[key] = {
                "participant_id": participant_id,
                "source_name": hit.get("name"),
                "spell_name": spell_name,
                "spell_slot": hit.get("spellSlot"),
                "basic": basic,
                "damage": 0,
            }
        damage = hit.get("physicalDamage", 0) + hit.get("magicDamage", 0) + hit.get("trueDamage", 0)
        grouped[key]["damage"] += damage
    sources = list(grouped.values())

    sources.sort(key=lambda source: source["damage"], reverse=True)

    return sources


def parse_frame(frame: dict, player_id: int, opponent_id: int | None) -> dict:
    """
    Parse player, opponent, and team context from one timeline frame.
    """
    player = parse_participant_frame(frame, player_id)
    opponent = parse_participant_frame(frame, opponent_id) if opponent_id is not None else None
    return {
        "timestamp": frame["timestamp"],
        "time": format_timestamp(frame["timestamp"]),
        "player": player,
        "opponent": opponent,
        "difference": {
            key: player[key] - opponent[key] if opponent else None
            for key in ("total_gold", "current_gold", "xp", "level", "lane_cs", "total_cs")
        },
        "participants": parse_all_participants(frame),
    }


def parse_frames(timeline: dict, player_id: int, opponent_id: int | None) -> list[dict]:
    """
    Parse the timeline's participant snapshots.
    """
    parsed_frames = []

    for frame in timeline["info"]["frames"]:
        parsed_frame = parse_frame(frame=frame, player_id=player_id, opponent_id=opponent_id)

        parsed_frames.append(parsed_frame)
    return sorted(parsed_frames, key=lambda frame: frame["timestamp"])


def create_base_event(event: dict) -> dict:
    """
    Extract shared event fields and participant involvement.
    """
    timestamp = event["timestamp"]

    return {"type": event["type"], "timestamp": timestamp, "time": format_timestamp(timestamp)}


def parse_champion_kill(event: dict, player_id: int, opponent_id: int | None) -> dict:
    """
    Parse a kill event and its reported damage sources.
    """
    parsed = create_base_event(event)
    assists = event.get("assistingParticipantIds", [])
    killer_id = event.get("killerId")
    victim_id = event.get("victimId")
    damage_sources = parse_damage_sources(event)

    parsed.update(
        {
            "killer_id": killer_id,
            "victim_id": victim_id,
            "assist_ids": assists,
            "damage_sources": damage_sources,
            "bounty": event.get("bounty"),
            "shutdown_bounty": event.get("shutdownBounty", 0),
            "position": parse_position(event.get("position")),
            "player_involved": (killer_id == player_id or victim_id == player_id or player_id in assists),
            "opponent_involved": (killer_id == opponent_id or victim_id == opponent_id or opponent_id in assists),
        }
    )

    return parsed


def parse_level_up(event: dict) -> dict:
    """
    Parse a player's level-up event.
    """
    parsed = create_base_event(event)

    parsed.update({"participant_id": event.get("participantId"), "level": event.get("level")})

    return parsed


def parse_item_event(event: dict) -> dict:
    """
    Parse an item purchase, sale, or undo event.
    """
    parsed = create_base_event(event)
    parsed["participant_id"] = event.get("participantId")

    if event["type"] == "ITEM_PURCHASED":
        parsed["item_id"] = event.get("itemId")
    elif event["type"] == "ITEM_SOLD":
        parsed["item_id"] = event.get("itemId")
    elif event["type"] == "ITEM_UNDO":
        parsed["before_id"] = event.get("beforeId")
        parsed["after_id"] = event.get("afterId")
        parsed["gold_gain"] = event.get("goldGain")
    return parsed


def parse_turret_plate(event: dict) -> dict:
    """
    Parse a turret plate destruction event.
    """
    parsed = create_base_event(event)

    parsed.update(
        {
            "killer_id": event.get("killerId"),
            "team_id": event.get("teamId"),
            "lane": event.get("laneType"),
            "position": parse_position(event.get("position")),
        }
    )

    return parsed


def parse_building_kill(event: dict) -> dict:
    """
    Parse a structure destruction event.
    """
    parsed = create_base_event(event)

    parsed.update(
        {
            "killer_id": event.get("killerId"),
            "assist_ids": event.get("assistingParticipantIds", []),
            "team_id": event.get("teamId"),
            "building_type": event.get("buildingType"),
            "tower_type": event.get("towerType"),
            "lane": event.get("laneType"),
            "bounty": event.get("bounty"),
            "position": parse_position(event.get("position")),
        }
    )

    return parsed


def parse_elite_monster_kill(event: dict) -> dict:
    """
    Parse a neutral objective capture event.
    """
    parsed = create_base_event(event)

    parsed.update(
        {
            "killer_id": event.get("killerId"),
            "killer_team_id": event.get("killerTeamId"),
            "assist_ids": event.get("assistingParticipantIds", []),
            "monster_type": event.get("monsterType"),
            "monster_sub_type": event.get("monsterSubType"),
            "position": parse_position(event.get("position")),
        }
    )

    return parsed


def parse_objective_bounty_event(event: dict) -> dict:
    """
    Parse an objective bounty state event.
    """
    parsed = create_base_event(event)

    parsed.update({"team_id": event.get("teamId"), "actual_start_time": event.get("actualStartTime")})

    return parsed


def parse_dragon_soul(event: dict) -> dict:
    """
    Parse a dragon soul award event.
    """
    parsed = create_base_event(event)

    parsed.update({"team_id": event.get("teamId"), "name": event.get("name")})

    return parsed


def parse_game_end(event: dict) -> dict:
    """
    Parse the observed game-end event.
    """
    parsed = create_base_event(event)

    parsed.update(
        {
            "winning_team": event.get("winningTeam"),
            "game_id": event.get("gameId"),
            "real_timestamp": event.get("realTimestamp"),
        }
    )

    return parsed


def parse_event(event: dict, player_id: int, opponent_id: int | None) -> dict | None:
    """
    Dispatch a supported timeline event to its parser.
    """
    event_type = event["type"]

    if event_type in {"WARD_PLACED", "WARD_KILL"}:
        return {
            **create_base_event(event),
            "creator_id": event.get("creatorId"),
            "killer_id": event.get("killerId"),
            "ward_type": event.get("wardType"),
            "position": parse_position(event.get("position")),
        }
    if event_type == "CHAMPION_KILL":
        return parse_champion_kill(event=event, player_id=player_id, opponent_id=opponent_id)
    if event_type == "LEVEL_UP":
        return parse_level_up(event)
    if event_type in {"ITEM_PURCHASED", "ITEM_SOLD", "ITEM_UNDO"}:
        return parse_item_event(event)
    if event_type == "TURRET_PLATE_DESTROYED":
        return parse_turret_plate(event)
    if event_type == "BUILDING_KILL":
        return parse_building_kill(event)
    if event_type == "ELITE_MONSTER_KILL":
        return parse_elite_monster_kill(event)
    if event_type in {"OBJECTIVE_BOUNTY_PRESTART", "OBJECTIVE_BOUNTY_FINISH"}:
        return parse_objective_bounty_event(event)
    if event_type == "DRAGON_SOUL_GIVEN":
        return parse_dragon_soul(event)
    if event_type == "GAME_END":
        return parse_game_end(event)
    return None


def parse_events(timeline: dict, player_id: int, opponent_id: int | None) -> list[dict]:
    """
    Collect supported events from the timeline frames.
    """
    parsed_events = []

    for frame in timeline["info"]["frames"]:
        for event in frame["events"]:
            event_type = event["type"]

            if event_type not in PLAYER_EVENT_TYPES and event_type not in GLOBAL_EVENT_TYPES:
                continue
            if event_type in PLAYER_EVENT_TYPES:
                participant_id = event.get("participantId")

                if participant_id not in {player_id, opponent_id}:
                    continue
            parsed_event = parse_event(event=event, player_id=player_id, opponent_id=opponent_id)

            if parsed_event is not None:
                parsed_events.append(parsed_event)
    return sorted(parsed_events, key=lambda event: event["timestamp"])


def parse_timeline(timeline: dict, player_id: int, opponent_id: int | None) -> dict:
    """
    Build structured timeline snapshots and events for analysis.
    """
    frames = parse_frames(timeline=timeline, player_id=player_id, opponent_id=opponent_id)
    events = parse_events(timeline=timeline, player_id=player_id, opponent_id=opponent_id)
    duration = 0

    if frames:
        duration = frames[-1]["timestamp"]
    return {
        "player_id": player_id,
        "opponent_id": opponent_id,
        "duration": duration,
        "duration_display": format_timestamp(duration),
        "frame_count": len(frames),
        "event_count": len(events),
        "frames": frames,
        "events": events,
    }


if __name__ == "__main__":
    from app.player_data.riot_api import get_account_by_riot_id, get_recent_match_ids, get_match, get_match_timeline

    account = get_account_by_riot_id(game_name="Cessereendya", tag_line="7944")
    puuid = account["puuid"]
    match_ids = get_recent_match_ids(puuid=puuid, count=1)

    if not match_ids:
        raise ValueError("No recent matches found.")
    match_id = match_ids[0]
    match = get_match(match_id)
    parsed_match = parse_match(match=match, puuid=puuid)

    if parsed_match["opponent"] is None:
        raise ValueError("Could not identify lane opponent.")
    player_id = parsed_match["player"]["participant_id"]
    opponent_id = parsed_match["opponent"]["participant_id"]
    timeline = get_match_timeline(match_id)
    parsed_timeline = parse_timeline(timeline=timeline, player_id=player_id, opponent_id=opponent_id)

    print(f"Match: {match_id}")
    print(f'{parsed_match["player"]["champion"]} ' f'vs {parsed_match["opponent"]["champion"]}')

    print()
    print(f'Frames: {parsed_timeline["frame_count"]}')
    print(f'Events kept: {parsed_timeline["event_count"]}')
    print(f'Duration: {parsed_timeline["duration_display"]}')

    print()
    print("Timeline:")

    for frame in parsed_timeline["frames"]:
        player = frame["player"]
        opponent = frame["opponent"]
        difference = frame["difference"]

        print(
            f'{frame["time"]:>5} | '
            f'Gold {player["total_gold"]:>5} '
            f'vs {opponent["total_gold"]:>5} '
            f'({difference["total_gold"]:+}) | '
            f'CS {player["total_cs"]:>3} '
            f'vs {opponent["total_cs"]:>3} '
            f'({difference["total_cs"]:+}) | '
            f'XP {difference["xp"]:+}'
        )
    print()
    print("All participants at 10:00:")

    frame_10 = parsed_timeline["frames"][10]

    for participant_id, participant in frame_10["participants"].items():
        print(
            f"Participant {participant_id}: "
            f'Level {participant["level"]} | '
            f'CS {participant["total_cs"]} | '
            f'Alive {participant["alive"]} | '
            f'Position {participant["position"]}'
        )
    print()
    print("Player combat events:")

    for event in parsed_timeline["events"]:
        if event["type"] != "CHAMPION_KILL":
            continue
        if not event["player_involved"]:
            continue
        if event["killer_id"] == player_id:
            result = "KILL"
        elif event["victim_id"] == player_id:
            result = "DEATH"
        else:
            result = "ASSIST"
        print(f'{event["time"]} | ' f"{result} | " f'Killer {event["killer_id"]} | ' f'Victim {event["victim_id"]}')
