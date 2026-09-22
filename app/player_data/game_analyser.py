from math import hypot

from app.player_data.queue_policy import (
    SUPPORTED_ANALYSIS_QUEUES, SWIFTPLAY_LIMITATION, require_supported_analysis_match,
)

from app.player_data.match_parser import parse_match
from app.player_data.timeline_parser import parse_timeline

ANALYSIS_VERSION = "4"


MAJOR_MATCHUP_GOLD_SWING = 500
MAJOR_TEAM_GOLD_SWING = 1000

LOW_FARM_THRESHOLD = 4
LOW_FARM_START_MINUTE = 10

LANE_PHASE_END = 14 * 60 * 1000

RECENT_DEATH_LOOKBACK = 90000

NEARBY_ALLY_RADIUS = 2500
NEARBY_ENEMY_RADIUS = 3000

FIGHT_EVENT_GAP = 30000
FIGHT_POSITION_DISTANCE = 3500
MAX_STATE_AGE = 30000
MILESTONE_SAMPLE_TOLERANCE = 5000
LOW_HEALTH_RATIO = 0.4
HIGH_UNSPENT_GOLD = 1500
FULL_BUILD_SPENT_GOLD = {"TOP": 20000, "MIDDLE": 20000, "JUNGLE": 20000, "BOTTOM": 23000, "UTILITY": 12000}
# These are event-observation windows, not reconstructed fight start/end times.
DEATH_OUTCOME_BEFORE_MS = 15000
DEATH_OUTCOME_AFTER_MS = 30000
DEATH_OBJECTIVE_AFTER_MS = 45000
EVENT_COVERAGE_MAX_GAP_MS = 65000
ALLIED_TURRET_CONTEXT_RADIUS = 1000
FIRST_WAVE_ARRIVAL = 98000
WAVE_INTERVAL = 30000
TEAMMATE_FARM_RATE = 6
OBJECTIVE_CONTEXT_RADIUS = 4000
LATE_GAME_START = 30 * 60000
LATE_GAME_STRUCTURE_LOSSES = 6

CONVERSION_WINDOW = 90000

LANE_ROLES = {"TOP", "MIDDLE", "BOTTOM"}

LIMITATIONS = [
    "Damage identity is reported evidence, not verified effect ownership; participant mapping and source names may conflict.",
    "Positions, health, gold and alive states are sampled, not exact event-time states.",
    "Kill damage records preserve reported damage; they do not identify the initiating cause or every CC.",
    "Wave cadence is a configurable approximation, not measured wave access or missed last hits.",
    "Fog of war, player knowledge, intent, exact respawns and safe resource availability are unknown.",
    "Spent gold is total minus current gold, not exact combat inventory value.",
    "Events after deaths/fights are temporal context; causality and decision quality are not established.",
    "Role counterparts and game phases are approximate; matchup comparisons weaken after lane phase.",
    "Threat semantics are deferred to downstream coaching; an empty important_spell_hits list is not evidence of no CC.",
    "Proximity uses same-frame historical positions; unavailable proximity is unknown, not no nearby allies.",
    "Sampled health/gold do not establish fight-entry health, overstay, safe recall or escape opportunities.",
    "Allied protection and spell availability are unknown; grouped damage does not identify individual casts.",
    "Death exchanges use bounded approximate kill clusters; temporal objective follow-up does not establish causality.",
    "Spending thresholds suppress gold coaching; they do not establish six completed items or a safe reset opportunity.",
]


def compact_event(event: dict) -> dict:
    """
    Remove detailed damage and involvement fields from an event.
    """
    return {
        key: value
        for key, value in event.items()
        if key not in {"damage_sources", "player_involved", "opponent_involved"}
    }


def compact_window(window: dict) -> dict:
    """
    Remove participant snapshots and compact events in a window.
    """
    return {
        key: ([compact_event(e) for e in value] if key == "events" else value)
        for key, value in window.items()
        if key not in {"end_participants", "start_participants", "participant_cs_gains", "participant_lane_cs_gains"}
    }


def estimate_lane_end(parsed_timeline: dict, parsed_match: dict) -> dict:
    """
    A lane tower loss is a transition signal, not proof that laning stopped.
    """
    lane = {"TOP": "TOP_LANE", "MIDDLE": "MID_LANE", "BOTTOM": "BOT_LANE"}.get(parsed_match["player"]["role"])
    towers = [
        e
        for e in parsed_timeline["events"]
        if e["type"] == "BUILDING_KILL"
        and e.get("building_type") == "TOWER_BUILDING"
        and e.get("tower_type") == "OUTER_TURRET"
        and e.get("lane") == lane
    ]
    timestamp = min([LANE_PHASE_END] + [e["timestamp"] for e in towers])
    return {
        "timestamp": min(timestamp, parsed_timeline["duration"]),
        "basis": "lane_outer_tower_loss" if timestamp < LANE_PHASE_END else "rough_time_benchmark",
        "confidence": 0.5,
    }


def game_state_at(timestamp: int, timeline: dict, match: dict) -> dict:
    """
    Summarize sampled game state and observed structures at a timestamp.
    """
    frame = find_frame_before(timeline["frames"], timestamp)
    teams = match["participant_teams"]
    player_team = teams[timeline["player_id"]]
    enemy_team = next((team for team in teams.values() if team != player_team), None)
    structures = [
        compact_event(e) for e in timeline["events"] if e["timestamp"] <= timestamp and e["type"] == "BUILDING_KILL"
    ]
    lane_end = estimate_lane_end(timeline, match)
    if match.get("map_id") not in {None, 11}:
        phase = "UNKNOWN"
    elif timestamp < lane_end["timestamp"]:
        phase = "LANE"
    elif timestamp < LANE_PHASE_END or not structures:
        phase = "TRANSITION"
    else:
        phase = (
            "LATE_GAME"
            if timestamp >= LATE_GAME_START and len(structures) >= LATE_GAME_STRUCTURE_LOSSES
            else "MID_GAME"
        )
    return {
        "match_id": match.get("match_id"),
        "map_id": match.get("map_id"),
        "queue_id": match.get("queue_id"),
        "game_version": match.get("game_version"),
        "player_role": match["player"]["role"],
        "player_team_id": player_team,
        "phase": {"label": phase, "confidence": 0.5, "basis": "time_and_observed_structure_losses"},
        "sample_timestamp": frame["timestamp"] if frame else None,
        "sample_age_ms": timestamp - frame["timestamp"] if frame else None,
        "sampled_alive": {pid: p["alive"] for pid, p in frame["participants"].items()} if frame else {},
        "team_gold": get_team_state(frame, player_team, enemy_team, teams) if frame else None,
        "matchup_difference": frame["difference"] if frame else None,
        "structure_losses_observed": structures,
        "structure_state_note": "loss history only; remaining positions and inhibitor respawns not reconstructed",
    }


def subtract_optional(after: int | None, before: int | None) -> int | None:
    """
    Subtract two values when both are known.
    """
    return after - before if after is not None and before is not None else None


def position_distance(position_a: dict | None, position_b: dict | None) -> float | None:
    """
    Calculate the distance between two known map positions.
    """
    if position_a is None or position_b is None:
        return None
    return hypot(position_a["x"] - position_b["x"], position_a["y"] - position_b["y"])


def get_events_between(events: list[dict], start_timestamp: int, end_timestamp: int) -> list[dict]:
    """
    Select events after the start and up to the end timestamp.
    """
    result = []

    for event in events:
        if start_timestamp < event["timestamp"] <= end_timestamp:
            result.append(event)
    return result


def find_frame_before(frames: list[dict], timestamp: int) -> dict | None:
    """
    Find the last frame at or before a timestamp.
    """
    result = None

    for frame in frames:
        if frame["timestamp"] > timestamp:
            break
        result = frame
    return result


def find_frame_after(frames: list[dict], timestamp: int) -> dict | None:
    """
    Find the first frame at or after a timestamp.
    """
    for frame in frames:
        if frame["timestamp"] >= timestamp:
            return frame
    return None


def find_nearest_frame(frames: list[dict], timestamp: int) -> dict | None:
    """
    Find the frame closest to a timestamp.
    """
    if not frames:
        return None
    return min(frames, key=lambda frame: abs(frame["timestamp"] - timestamp))


def get_team_gold(frame: dict, team_id: int, participant_teams: dict[int, int]) -> int:
    """
    Sum sampled gold for participants on the requested team.
    """
    total = 0

    for participant_id, participant in frame["participants"].items():
        if participant_teams.get(participant_id) == team_id:
            total += participant["total_gold"]
    return total


def get_team_state(frame: dict, player_team_id: int, enemy_team_id: int, participant_teams: dict[int, int]) -> dict:
    """
    Compare the two teams' sampled gold totals.
    """
    player_team_gold = get_team_gold(frame, player_team_id, participant_teams)
    enemy_team_gold = get_team_gold(frame, enemy_team_id, participant_teams)

    return {
        "player_team_gold": player_team_gold,
        "enemy_team_gold": enemy_team_gold,
        "team_gold_diff": (player_team_gold - enemy_team_gold),
    }


def get_player_combat_result(event: dict, player_id: int) -> str | None:
    """
    Identify the player's kill, death, or assist in an event.
    """
    if event["type"] != "CHAMPION_KILL":
        return None
    if event["killer_id"] == player_id:
        return "KILL"
    if event["victim_id"] == player_id:
        return "DEATH"
    if player_id in event["assist_ids"]:
        return "ASSIST"
    return None


def get_event_team(event: dict, participant_teams: dict[int, int]) -> int | None:
    """
    Return the gaining team; structure team_id identifies the losing team.
    """
    if event["type"] == "ELITE_MONSTER_KILL":
        return event.get("killer_team_id") or participant_teams.get(event.get("killer_id"))
    if event["type"] in {"BUILDING_KILL", "TURRET_PLATE_DESTROYED"}:
        owner = event.get("team_id")
        others = set(participant_teams.values()) - {owner}
        if owner in participant_teams.values() and len(others) == 1:
            return others.pop()
    return participant_teams.get(event.get("killer_id"))


def create_window(start_frame: dict, end_frame: dict, events: list[dict], parsed_match: dict, player_id: int,
                  opponent_id: int | None) -> dict:
    """
    Build analysis evidence between two timeline frames.
    """
    participant_teams = parsed_match["participant_teams"]
    player_team_id = participant_teams[player_id]
    enemy_team_id = next((team for team in participant_teams.values() if team != player_team_id), None)
    start_team = get_team_state(start_frame, player_team_id, enemy_team_id, participant_teams)
    end_team = get_team_state(end_frame, player_team_id, enemy_team_id, participant_teams)
    player_start = start_frame["player"]
    player_end = end_frame["player"]
    opponent_start = start_frame["opponent"]
    opponent_end = end_frame["opponent"]
    window_events = get_events_between(events, start_frame["timestamp"], end_frame["timestamp"])
    player_kills = 0
    player_deaths = 0
    player_assists = 0

    for event in window_events:
        result = get_player_combat_result(event, player_id)

        if result == "KILL":
            player_kills += 1
        elif result == "DEATH":
            player_deaths += 1
        elif result == "ASSIST":
            player_assists += 1
    participant_cs_gains = {}

    for participant_id in start_frame["participants"]:
        start_state = start_frame["participants"][participant_id]
        end_state = end_frame["participants"].get(participant_id)

        if end_state is None:
            continue
        participant_cs_gains[participant_id] = end_state["total_cs"] - start_state["total_cs"]
    return {
        "start_time": start_frame["time"],
        "end_time": end_frame["time"],
        "start_timestamp": start_frame["timestamp"],
        "end_timestamp": end_frame["timestamp"],
        "matchup_gold_diff_before": (start_frame["difference"]["total_gold"]),
        "matchup_gold_diff_after": (end_frame["difference"]["total_gold"]),
        "matchup_gold_diff_change": (
            subtract_optional(end_frame["difference"]["total_gold"], start_frame["difference"]["total_gold"])
        ),
        "team_gold_diff_before": (start_team["team_gold_diff"]),
        "team_gold_diff_after": (end_team["team_gold_diff"]),
        "team_gold_diff_change": (end_team["team_gold_diff"] - start_team["team_gold_diff"]),
        "player_gold_gained": (player_end["total_gold"] - player_start["total_gold"]),
        "opponent_gold_gained": (
            (opponent_end["total_gold"] - opponent_start["total_gold"]) if opponent_end and opponent_start else None
        ),
        "player_cs_gained": (player_end["total_cs"] - player_start["total_cs"]),
        "opponent_cs_gained": (
            (opponent_end["total_cs"] - opponent_start["total_cs"]) if opponent_end and opponent_start else None
        ),
        "player_xp_gained": (player_end["xp"] - player_start["xp"]),
        "opponent_xp_gained": (
            (opponent_end["xp"] - opponent_start["xp"]) if opponent_end and opponent_start else None
        ),
        "player_kills": player_kills,
        "player_deaths": player_deaths,
        "player_assists": player_assists,
        "participant_cs_gains": participant_cs_gains,
        "participant_lane_cs_gains": {
            pid: end_frame["participants"][pid]["lane_cs"] - state["lane_cs"]
            for pid, state in start_frame["participants"].items()
            if pid in end_frame["participants"]
        },
        "start_participants": start_frame["participants"],
        "player_start_position": (player_start["position"]),
        "player_end_position": (player_end["position"]),
        "end_participants": (end_frame["participants"]),
        "events": window_events,
    }


def create_windows(parsed_timeline: dict, parsed_match: dict) -> list[dict]:
    """
    Build analysis windows from successive timeline frames.
    """
    frames = parsed_timeline["frames"]
    windows = []

    for index in range(len(frames) - 1):
        windows.append(
            create_window(
                start_frame=frames[index],
                end_frame=frames[index + 1],
                events=parsed_timeline["events"],
                parsed_match=parsed_match,
                player_id=parsed_timeline["player_id"],
                opponent_id=parsed_timeline["opponent_id"],
            )
        )
    return windows


def estimate_lane_waves(timestamp: int) -> int:
    """
    Estimate wave arrivals using the configured cadence.
    """
    return max(0, 1 + (timestamp - FIRST_WAVE_ARRIVAL) // WAVE_INTERVAL)


def find_milestone_frame(frames: list[dict], timestamp: int) -> dict | None:
    """
    Allow small snapshot drift for benchmarks, never for pre-death state.
    """
    frame = find_nearest_frame(frames, timestamp)
    if frame and abs(frame["timestamp"] - timestamp) <= MILESTONE_SAMPLE_TOLERANCE:
        return frame
    return None


def analyze_cs(parsed_timeline: dict, parsed_match: dict) -> dict:
    """
    Calculate farming metrics with their sampling and wave assumptions.
    """
    frames = parsed_timeline["frames"]
    player = parsed_match["player"]
    duration = parsed_match.get("game_duration", parsed_timeline["duration"] / 1000)
    total_cs = player.get("cs", frames[-1]["player"]["total_cs"] if frames else 0)
    result = {
        "overall_cs": total_cs,
        "overall_cs_per_min": round(total_cs / (duration / 60), 2) if duration > 0 else None,
        "total_lane_minions": player.get("lane_cs"),
        "lane_cs": None,
        "lane_cs_per_wave": None,
        "estimated_lane_waves": None,
        "post_lane_cs_per_min": None,
        "matchup_cs_diff_at_10": None,
        "matchup_gold_diff_at_10": None,
        "matchup_xp_diff_at_10": None,
        "metric_kind": "derived_metrics",
        "lane_boundary": estimate_lane_end(parsed_timeline, parsed_match),
        "wave_assumption": {
            "first_arrival_ms": FIRST_WAVE_ARRIVAL,
            "interval_ms": WAVE_INTERVAL,
            "actual_access": "unknown",
        },
        "overall_source": "match_summary" if "cs" in player else "last_timeline_sample",
    }
    if parsed_match.get("queue_id") == 480:
        result["lane_boundary"] = {"timestamp": None, "basis": "swiftplay_not_calibrated", "confidence": 0}
        result["wave_assumption"] = {"actual_access": "unknown", "status": "swiftplay_not_calibrated"}
    if not frames:
        return result
    if duration >= 10 * 60:
        frame_10 = find_milestone_frame(frames, 10 * 60000)
        if frame_10:
            result["matchup_cs_diff_at_10"] = frame_10["difference"]["total_cs"]
            result["matchup_gold_diff_at_10"] = frame_10["difference"]["total_gold"]
            result["matchup_xp_diff_at_10"] = frame_10["difference"]["xp"]
            result["matchup_cs_sample_timestamp"] = frame_10["timestamp"]
            result["matchup_cs_sample_offset_ms"] = frame_10["timestamp"] - 10 * 60000
    if parsed_match.get("queue_id") == 480:
        return result
    if player["role"] not in LANE_ROLES or parsed_match.get("map_id") not in {None, 11}:
        return result
    target = result["lane_boundary"]["timestamp"]
    lane_end = find_milestone_frame(frames, target)
    # A tower-loss boundary need not coincide with a nominal minute snapshot.
    if lane_end is None and result["lane_boundary"]["basis"] == "lane_outer_tower_loss":
        lane_end = find_frame_before(frames, target)
    if lane_end is None:
        return result
    result["lane_boundary"]["sample_timestamp"] = lane_end["timestamp"]
    result["lane_boundary"]["sample_offset_ms"] = lane_end["timestamp"] - target
    lane_cs = lane_end["player"]["lane_cs"]
    waves = estimate_lane_waves(lane_end["timestamp"])
    result.update(
        lane_cs=lane_cs, estimated_lane_waves=waves, lane_cs_per_wave=round(lane_cs / waves, 2) if waves else None
    )
    post_minutes = (duration * 1000 - lane_end["timestamp"]) / 60000
    if post_minutes > 0 and result["lane_boundary"]["timestamp"] < parsed_timeline["duration"]:
        result["post_lane_cs_per_min"] = round((total_cs - lane_end["player"]["total_cs"]) / post_minutes, 2)
    return result


def player_died_recently(window: dict, parsed_timeline: dict) -> bool:
    """
    Check for a recent player death before a timestamp.
    """
    start = window["start_timestamp"]
    deaths = [
        event
        for event in parsed_timeline["events"]
        if event["type"] == "CHAMPION_KILL"
        and event["victim_id"] == parsed_timeline["player_id"]
        and event["timestamp"] <= start
    ]
    if not deaths:
        return False
    death = max(deaths, key=lambda e: e["timestamp"])
    samples = [f for f in parsed_timeline["frames"] if death["timestamp"] < f["timestamp"] <= start]
    # Observed CS gain while alive proves resumed resource collection, not an exact respawn time.

    for previous, current in zip(samples, samples[1:]):
        if current["player"]["alive"] is True and current["player"]["total_cs"] > previous["player"]["total_cs"]:
            return False
    if samples and samples[-1]["player"]["alive"] is False:
        return True
    return start - death["timestamp"] <= RECENT_DEATH_LOOKBACK


def classify_low_farm_window(window: dict, parsed_timeline: dict, parsed_match: dict) -> dict | None:
    """
    Classify a low-farm window using available evidence.
    """
    player_id = parsed_timeline["player_id"]
    start_minute = window["start_timestamp"] // 60000

    if start_minute < LOW_FARM_START_MINUTE:
        return None
    duration_minutes = (window["end_timestamp"] - window["start_timestamp"]) / 60000
    if duration_minutes <= 0:
        return None
    if window["player_cs_gained"] / duration_minutes > LOW_FARM_THRESHOLD:
        return None

    if parsed_match["player"]["role"] == "UTILITY":
        return {"reason": "support_role_low_cs_not_diagnostic", "kind": "context"}
    if window["player_deaths"] > 0:
        return {"reason": "death_during_window", "kind": "fact"}
    if player_died_recently(window, parsed_timeline):
        return {
            "reason": "post_death_downtime",
            "confidence": 0.7,
            "basis": "recent_death_or_sampled_dead; exact_respawn_unknown",
        }
    if window["player_kills"] > 0 or window["player_assists"] > 0:
        return {"reason": "combat_window", "kind": "fact"}
    if any(e["type"] == "GAME_END" for e in window["events"]):
        return {"reason": "game_ending_window", "kind": "fact"}
    if any(
        e["type"] in {"ITEM_PURCHASED", "ITEM_SOLD", "ITEM_UNDO"} and e.get("participant_id") == player_id
        for e in window["events"]
    ):
        return {
            "reason": "possible_shopping_downtime",
            "confidence": 0.6,
            "evidence": "item_transaction_in_window; recall_not_observed",
        }
    if any(
        state.get(player_id, {}).get("alive") is False
        for state in (window.get("start_participants", {}), window["end_participants"])
    ):
        return {"reason": "sampled_dead_in_window", "kind": "fact"}
    for event in window["events"]:
        if event["type"] == "ELITE_MONSTER_KILL" and (
            event.get("killer_id") == player_id or player_id in event.get("assist_ids", [])
        ):
            return {"reason": "objective_participation", "kind": "fact", "timestamp": event["timestamp"]}
    player_position = window["player_end_position"]
    participant_teams = parsed_match["participant_teams"]
    player_team = participant_teams[player_id]

    for participant_id, cs_gain in window.get("participant_lane_cs_gains", {}).items():
        if participant_id == player_id:
            continue
        if participant_teams.get(participant_id) != player_team:
            continue
        if cs_gain / duration_minutes < TEAMMATE_FARM_RATE:
            continue
        teammate = window["end_participants"].get(participant_id)

        if teammate is None:
            continue
        distance = position_distance(player_position, teammate["position"])
        teammate_start = window.get("start_participants", {}).get(participant_id, {})
        start_distance = position_distance(window["player_start_position"], teammate_start.get("position"))
        if (
            distance is not None
            and distance <= NEARBY_ALLY_RADIUS
            and start_distance is not None
            and start_distance <= NEARBY_ALLY_RADIUS
            and teammate.get("alive") is True
            and teammate_start.get("alive") is True
        ):
            return {
                "reason": "possible_teammate_wave_absorption",
                "confidence": 0.5,
                "teammate_id": participant_id,
                "teammate_cs_gain": cs_gain,
            }
    for event in window["events"]:
        if event["type"] != "ELITE_MONSTER_KILL":
            continue
        event_position = event.get("position")
        distance = position_distance(player_position, event_position)
        sample_age = window["end_timestamp"] - event["timestamp"]
        if distance is not None and distance <= OBJECTIVE_CONTEXT_RADIUS and sample_age <= MAX_STATE_AGE:
            return {"reason": "possible_objective_window", "confidence": 0.5, "objective": event.get("monster_type")}

    ally_counts = []
    for key, position in [
        ("start_participants", window["player_start_position"]),
        ("end_participants", window["player_end_position"]),
    ]:
        nearby = nearby_players(position, {"participants": window.get(key, {})}, player_id, participant_teams)
        ally_counts.append(len(nearby["allies"]))
    if min(ally_counts) >= 3:
        return {
            "reason": "possible_grouping_downtime",
            "confidence": 0.5,
            "evidence": {"sampled_nearby_ally_counts": ally_counts},
        }
    return {"reason": "unexplained_low_farm", "confidence": 0.5}


def analyze_farm_windows(windows: list[dict], parsed_timeline: dict, parsed_match: dict) -> list[dict]:
    """
    Review low-farm windows and retain their supporting evidence.
    """
    results = []

    for window in windows:
        classification = classify_low_farm_window(window, parsed_timeline, parsed_match)

        if classification is None:
            continue
        results.append(
            {
                "start_time": window["start_time"],
                "end_time": window["end_time"],
                "start_timestamp": window["start_timestamp"],
                "end_timestamp": window["end_timestamp"],
                "game_phase": game_state_at(window["start_timestamp"], parsed_timeline, parsed_match)["phase"]["label"],
                "player_cs_gained": (window["player_cs_gained"]),
                "opponent_cs_gained": (window["opponent_cs_gained"]),
                "player_gold_gained": (window["player_gold_gained"]),
                "classification": classification,
            }
        )
    return results


def nearby_players(death_position: dict, frame: dict, player_id: int, participant_teams: dict[int, int]) -> dict:
    """
    Find sampled participants within the requested distance.
    """
    player_team = participant_teams[player_id]
    allies = []
    enemies = []

    for participant_id, state in frame["participants"].items():
        if participant_id == player_id:
            continue
        if not state["alive"]:
            continue
        distance = position_distance(death_position, state["position"])

        if distance is None:
            continue
        if participant_teams.get(participant_id) == player_team:
            if distance <= NEARBY_ALLY_RADIUS:
                allies.append({"participant_id": participant_id, "distance": round(distance)})
        else:
            if distance <= NEARBY_ENEMY_RADIUS:
                enemies.append({"participant_id": participant_id, "distance": round(distance)})
    return {"allies": allies, "enemies": enemies}


def death_proximity_snapshot(frame: dict | None, timestamp: int, player_id: int, match: dict,
                             valid_current_life: bool = True) -> dict:
    """
    Measure same-frame proximity while separating historical observations from unavailable evidence.
    """
    sample_time = frame["timestamp"] if frame else None
    age = timestamp - sample_time if sample_time is not None else None
    position = frame["player"].get("position") if frame else None
    result = {
        "status": "unavailable", "snapshot_timestamp": sample_time, "sample_age_ms": age,
        "player_position": position, "interpretation": "historical_snapshot_only; death_time_proximity_unknown",
        "allies": None, "enemies": None, "ally_status": "unavailable", "enemy_status": "unavailable",
        "ally_radius": NEARBY_ALLY_RADIUS, "enemy_radius": NEARBY_ENEMY_RADIUS,
    }
    if frame is None or position is None:
        result["reason"] = "missing_snapshot_or_player_position"
        return result

    player_team = match["participant_teams"][player_id]
    groups = {"allies": [], "enemies": []}
    complete = {"allies": True, "enemies": True}
    for pid, team in match["participant_teams"].items():
        if pid == player_id:
            continue
        group = "allies" if team == player_team else "enemies"
        participant = frame["participants"].get(pid)
        if participant is None or participant.get("alive") is None:
            complete[group] = False
            continue
        if participant["alive"] is False:
            continue
        distance = position_distance(position, participant.get("position"))
        if distance is None:
            complete[group] = False
            continue
        radius = NEARBY_ALLY_RADIUS if group == "allies" else NEARBY_ENEMY_RADIUS
        if distance <= radius:
            groups[group].append({"participant_id": pid, "champion": match["participant_info"].get(pid, {}).get("champion"),
                                  "distance": round(distance)})

    reliable = valid_current_life and frame["player"].get("alive") is True and 0 <= age <= MAX_STATE_AGE
    for group, status_key in (("allies", "ally_status"), ("enemies", "enemy_status")):
        if reliable and complete[group]:
            result[group] = groups[group]
            result[status_key] = "observed_historical_snapshot"
        else:
            # Preserve known distances without treating partial coverage as proof of absence.
            result["historical_observed_" + group] = groups[group]
            result[status_key] = "unavailable_for_current_encounter" if not reliable else "incomplete_snapshot"
    result["status"] = (
        "observed_historical_snapshot" if reliable and all(complete.values())
        else "partial_historical_snapshot" if reliable else "unavailable_for_current_encounter"
    )
    result["reason"] = ("snapshot_only_not_encounter_history" if reliable else
                        "stale_snapshot_or_unknown_alive_state_or_previous_life")
    return result


def has_effectively_completed_build(role: str, total_gold_spent: int | None) -> bool:
    """
    Return whether recorded spending crosses the role's gold-coaching suppression threshold, not inventory completion.
    """
    threshold = FULL_BUILD_SPENT_GOLD.get(role)
    return threshold is not None and total_gold_spent is not None and total_gold_spent >= threshold


def unspent_gold_context(role: str, state: dict | None) -> dict:
    """
    Preserve gold measurements while identifying whether spending-based coaching must be suppressed.
    """
    state = state or {}
    total = state.get("total_gold")
    current = state.get("current_gold")
    spent = total - current if total is not None and current is not None and total >= current else None
    threshold = FULL_BUILD_SPENT_GOLD.get(role)
    reached = has_effectively_completed_build(role, spent)
    known = threshold is not None and spent is not None
    return {
        "role": role,
        "total_gold_spent": spent,
        "current_unspent_gold": current,
        "spent_gold_basis": "snapshot_total_gold_minus_current_gold; net_spending_estimate_not_inventory_value",
        "role_spending_threshold": threshold,
        "threshold_reached": reached if known else None,
        "suppress_unspent_gold_coaching": reached or not known,
        "reason": (
            "effective_full_build_spending_threshold"
            if reached
            else "below_threshold" if known else "unknown_role_or_spending"
        ),
        "interpretation": "threshold_is_not_proof_of_full_inventory; unspent_gold_never_proves_safe_reset_opportunity",
    }


def create_death_cause_candidates(death: dict) -> list[dict]:
    """
    Retain neutral historical observations in the legacy candidate container without asserting causes.
    """
    candidates = []
    quality = death.get("evidence_quality", {})
    age = quality.get("state_age_ms")
    state = death.get("state_before_death") or {}
    fresh_state = bool(state) and age is not None and 0 <= age <= MAX_STATE_AGE
    proximity = death.get("proximity_snapshot", {})
    if proximity.get("allies") == []:
        candidates.append({
            "type": "limited_allied_proximity_in_last_snapshot", "kind": "derived_observation",
            "valence": "observation", "evidence": proximity,
            "interpretation": "historical_snapshot_only; isolation_positioning_error_and_peel_quality_not_established",
        })
    if fresh_state and 0 < (death.get("health_ratio_before") or 0) <= LOW_HEALTH_RATIO:
        candidates.append({
            "type": "low_sampled_health", "kind": "derived_observation", "valence": "observation",
            "evidence": {"health": state.get("health"), "sampled_health_ratio": death["health_ratio_before"],
                         "snapshot_timestamp": state.get("sample_timestamp"), "sample_age_ms": age},
            "interpretation": "historical_snapshot_only; fight_entry_health_and_overstay_not_established",
        })
    if (fresh_state and (state.get("current_gold") or 0) >= HIGH_UNSPENT_GOLD
            and not death.get("unspent_gold_context", {}).get("suppress_unspent_gold_coaching", True)):
        candidates.append({
            "type": "large_unspent_gold", "kind": "derived_observation", "valence": "observation",
            "evidence": {"unspent_gold": state["current_gold"], "snapshot_timestamp": state.get("sample_timestamp"),
                         "sample_age_ms": age, "spending_context": death["unspent_gold_context"]},
            "interpretation": "historical_snapshot_only; safe_recall_opportunity_and_overstay_not_established",
        })
    return candidates


def annotate_damage_sources(sources: list[dict], match: dict, player_team: int) -> list[dict]:
    """
    Preserve Riot attribution without interpreting item/environment ownership.
    """
    results = []
    for source in sources:
        pid = source.get("participant_id")
        team = match["participant_teams"].get(pid)
        info = match["participant_info"].get(pid, {})
        relation = "unknown" if team is None else ("allied" if team == player_team else "enemy")
        normalize = lambda name: "".join(c for c in (name or "").lower() if c.isalnum())
        reported_name = normalize(source.get("source_name"))
        known_names = {normalize(p.get("champion")) for p in match["participant_info"].values()}
        conflict = bool(
            reported_name
            and reported_name in known_names
            and info.get("champion")
            and reported_name != normalize(info["champion"])
        )
        entry = {
            **source,
            "champion": info.get("champion") if not conflict else None,
            "role": info.get("role") if not conflict else None,
            "source_team_id": team,
            "source_team_relation": relation,
            "resolved_participant_id": pid if team is not None and not conflict else None,
            "resolved_team_relation": relation if not conflict else "unknown",
            "interpretation": "recorded_damage_involvement_only; does_not_establish_initiation_or_cause",
            "damage_semantics": "grouped_reported_total; may_include_multiple_hits_or_casts; cast_count_unknown",
        }
        if conflict:
            entry.update(attribution_status="identity_conflict", participant_champion=info.get("champion"))
        elif relation == "allied":
            entry["interpretation_note"] = "does_not_establish_allied_attack"
        results.append(entry)
    return results


def outcome_window_metadata(death_timestamp: int, duration: int, before: dict | None, later: dict | None) -> dict:
    """
    Describe observed coverage of an outcome window.
    """
    observed_end = min(death_timestamp + CONVERSION_WINDOW, duration)
    start = before["timestamp"] if before else None
    end = later["timestamp"] if later else None
    available = start is not None and end is not None and end > start
    coverage = max(0, min(end, observed_end) - max(start, death_timestamp)) if available else 0
    return {
        "event_window": {
            "start_exclusive": death_timestamp,
            "end_inclusive": observed_end,
            "requested_duration_ms": CONVERSION_WINDOW,
            "observed_duration_ms": max(0, observed_end - death_timestamp),
        },
        "gold_window": {
            "sample_start": start,
            "sample_end": end,
            "sample_duration_ms": end - start if available else None,
            "pre_death_included_ms": death_timestamp - start if available else None,
            "post_death_covered_ms": coverage,
            "uncovered_event_tail_ms": max(0, observed_end - max(death_timestamp, end)) if available else None,
            "available": available,
        },
        "window_comparison": "gold_and_events_have_different_bounds; no_interpolation",
    }


def fight_cluster_id(fight: list[dict]) -> str:
    """
    Identify an approximate kill cluster using its first recorded death.
    """
    first = fight[0]
    return f"fight_{first['timestamp']}_{first.get('victim_id')}"


def event_window_coverage(timeline: dict, start: int, end: int) -> dict:
    """
    Describe frame coverage of an event window without assuming missing frames contain no events.
    """
    frames = timeline["frames"]
    observed_start = max(start, frames[0]["timestamp"]) if frames else None
    observed_end = min(end, timeline["duration"]) if frames else None
    complete = bool(frames and frames[0]["timestamp"] <= start and timeline["duration"] >= end)
    for before, after in zip(frames, frames[1:]):
        if before["timestamp"] < end and after["timestamp"] > start:
            if after["timestamp"] - before["timestamp"] > EVENT_COVERAGE_MAX_GAP_MS:
                complete = False
    return {
        "requested_start_ms": start,
        "requested_end_ms": end,
        "observed_start_ms": observed_start,
        "observed_end_ms": observed_end,
        "complete": complete,
        "basis": "timeline_frame_coverage; absence_means_no_recorded_event_not_proof_of_prevention",
    }


def kill_exchange_summary(kills: list[dict], player_id: int, match: dict, death_timestamp: int) -> dict:
    """
    Count recorded combat results and participant identities within an explicitly selected exchange.
    """
    teams = match["participant_teams"]
    own = teams[player_id]
    enemy = next((team for team in teams.values() if team != own), None)
    deaths = []
    allied_kills = enemy_kills = player_kills = player_assists = 0
    player_kill_timing = {"before": 0, "at": 0, "after": 0}
    known = True
    for kill in kills:
        killer_team = teams.get(kill.get("killer_id"))
        victim_id = kill.get("victim_id")
        victim_team = teams.get(victim_id)
        known = known and killer_team in {own, enemy} and victim_team in {own, enemy} and killer_team != victim_team
        allied_kills += int(killer_team == own and victim_team == enemy)
        enemy_kills += int(killer_team == enemy and victim_team == own)
        personal_kill = kill.get("killer_id") == player_id and victim_team == enemy
        player_kills += int(personal_kill)
        player_assists += int(player_id in kill.get("assist_ids", []) and victim_team == enemy and not personal_kill)
        when = (
            "before"
            if kill["timestamp"] < death_timestamp
            else "after" if kill["timestamp"] > death_timestamp else "at"
        )
        player_kill_timing[when] += int(personal_kill)
        info = match["participant_info"].get(victim_id, {})
        deaths.append(
            {
                "timestamp": kill["timestamp"],
                "participant_id": victim_id,
                "champion": info.get("champion"),
                "role": info.get("role"),
                "team_id": victim_team,
                "killer_id": kill.get("killer_id"),
                "bounty": kill.get("bounty"),
                "shutdown_bounty": kill.get("shutdown_bounty"),
            }
        )
    participants = fight_participant_evidence(kills, match)
    participant_ids = [item["participant_id"] for item in participants]
    player_deaths = sum(kill.get("victim_id") == player_id for kill in kills)
    return {
        "player_kills": player_kills,
        "player_assists": player_assists,
        "player_deaths": player_deaths,
        "player_kills_by_timing": player_kill_timing,
        "allied_kills": allied_kills,
        "enemy_kills": enemy_kills,
        "personal_kill_trade": {
            "kills": player_kills,
            "deaths": player_deaths,
            "differential": player_kills - player_deaths,
        },
        "team_kill_differential": allied_kills - enemy_kills,
        "recorded_deaths": deaths,
        "enemy_champions_killed": [d for d in deaths if d["team_id"] == enemy],
        "allied_champions_killed": [d for d in deaths if d["team_id"] == own],
        "participant_evidence": participants,
        "recorded_enemy_participants": sum(teams[pid] == enemy for pid in participant_ids),
        "recorded_allied_participants": sum(teams[pid] == own for pid in participant_ids),
        "participant_count_semantics": "recorded_contributors_only; not_exact_fight_numbers_or_protection",
        "kill_attribution_complete": bool(known),
    }


def death_location_context(event: dict, timeline: dict, match: dict, player_team: int) -> dict:
    """
    Identify proximity to a recorded standing allied turret without inferring defensive intent.
    """
    result = {
        "near_allied_turret": None,
        "turret_distance": None,
        "status": "unknown",
        "interpretation": "location_only; wave_collection_intent_and_turret_protection_unknown",
    }
    if match.get("map_id") != 11 or event.get("position") is None:
        return result
    # Outer/inner turrets have fixed positions. A later destruction record locates a turret still standing here.
    # Do not use Nexus/inhibitor turret records, whose reconstruction may require respawn mechanics.
    candidates = []
    for structure in timeline["events"]:
        if (
            structure["type"] != "BUILDING_KILL"
            or structure.get("building_type") != "TOWER_BUILDING"
            or structure.get("team_id") != player_team
            or structure.get("tower_type") not in {"OUTER_TURRET", "INNER_TURRET"}
            or structure["timestamp"] <= event["timestamp"]
        ):
            continue
        distance = position_distance(event.get("position"), structure.get("position"))
        if distance is not None and distance <= ALLIED_TURRET_CONTEXT_RADIUS:
            candidates.append((distance, structure))
    if candidates:
        distance, structure = min(candidates, key=lambda item: item[0])
        result.update(
            near_allied_turret=True,
            turret_distance=round(distance),
            status="derived_structure_observation",
            turret_position=structure["position"],
            tower_type=structure["tower_type"],
            lane=structure.get("lane"),
            destruction_timestamp=structure["timestamp"],
            radius=ALLIED_TURRET_CONTEXT_RADIUS,
            basis="fixed_outer_or_inner_turret_position_from_later_destruction_record",
        )
    # No matching record does not establish that no other allied turret was nearby.
    return result


def death_objective_context(timestamp: int, timeline: dict, match: dict, own: int, enemy: int) -> dict:
    """
    Describe observed objective follow-up and known dragon counts without inferring prevention or availability.
    """
    end = timestamp + DEATH_OBJECTIVE_AFTER_MS
    coverage = event_window_coverage(timeline, timestamp, end)
    objectives = []
    structures = []
    for event in get_events_between(timeline["events"], timestamp, min(end, timeline["duration"])):
        if event["type"] not in {"ELITE_MONSTER_KILL", "BUILDING_KILL"}:
            continue
        entry = {**compact_event(event), "gaining_team_id": get_event_team(event, match["participant_teams"])}
        (objectives if event["type"] == "ELITE_MONSTER_KILL" else structures).append(entry)
    followups = objectives + structures
    known_teams = all(event["gaining_team_id"] in {own, enemy} for event in followups)
    enemy_followup = any(event["gaining_team_id"] == enemy for event in followups)
    allied_followup = any(event["gaining_team_id"] == own for event in followups)
    absence_known = coverage["complete"] and known_teams
    prior_dragons = [
        event
        for event in timeline["events"]
        if event["timestamp"] <= timestamp
        and event["type"] == "ELITE_MONSTER_KILL"
        and event.get("monster_type") == "DRAGON"
    ]
    elemental = [
        event
        for event in prior_dragons
        if event.get("monster_sub_type")
        in {"AIR_DRAGON", "EARTH_DRAGON", "FIRE_DRAGON", "WATER_DRAGON", "CHEMTECH_DRAGON", "HEXTECH_DRAGON"}
    ]
    full_history = event_window_coverage(timeline, 0, timestamp)["complete"]
    known_dragons = all(
        event.get("monster_sub_type")
        in {
            "AIR_DRAGON",
            "EARTH_DRAGON",
            "FIRE_DRAGON",
            "WATER_DRAGON",
            "CHEMTECH_DRAGON",
            "HEXTECH_DRAGON",
            "ELDER_DRAGON",
        }
        and get_event_team(event, match["participant_teams"]) in {own, enemy}
        for event in prior_dragons
    )
    enemy_dragons = sum(get_event_team(event, match["participant_teams"]) == enemy for event in elemental)
    soul_already_awarded = any(
        event["timestamp"] <= timestamp and event["type"] == "DRAGON_SOUL_GIVEN" for event in timeline["events"]
    )
    any_team_has_four = any(
        sum(get_event_team(event, match["participant_teams"]) == team for event in elemental) >= 4
        for team in (own, enemy)
    )
    dragon_captured = any(
        event.get("monster_type") == "DRAGON" and event["gaining_team_id"] == enemy for event in objectives
    )
    elder_observed = any(event.get("monster_sub_type") == "ELDER_DRAGON" for event in prior_dragons)
    soul_known = full_history and known_dragons and match.get("map_id") == 11 and match.get("queue_id") != 480
    return {
        "window_after_ms": DEATH_OBJECTIVE_AFTER_MS,
        "anchor": "death_timestamp",
        "coverage": coverage,
        "objectives_after": objectives,
        "structures_after": structures,
        "enemy_objective_followup": True if enemy_followup else False if absence_known else None,
        "allied_objective_followup": True if allied_followup else False if absence_known else None,
        "dragon_context": {
            "dragon_available": None,
            "enemy_elemental_dragons_recorded": enemy_dragons,
            "enemy_next_elemental_dragon_would_grant_soul": (
                enemy_dragons == 3 and not soul_already_awarded and not any_team_has_four and not elder_observed
                if soul_known
                else None
            ),
            "enemy_dragon_captured_after_death": True if dragon_captured else False if absence_known else None,
            "count_coverage_complete": bool(soul_known),
        },
        "interpretation": "temporal_followup_only; absence_does_not_establish_prevention; safe_availability_unknown",
    }


def build_death_outcome(event: dict, timeline: dict, match: dict) -> dict:
    """
    Build an independent bounded exchange and objective context for one death without causal judgments.
    """
    timestamp = event["timestamp"]
    start = max(0, timestamp - DEATH_OUTCOME_BEFORE_MS)
    end = timestamp + DEATH_OUTCOME_AFTER_MS
    player_id = timeline["player_id"]
    teams = match["participant_teams"]
    own = teams[player_id]
    enemy = next((team for team in teams.values() if team != own), None)
    clusters = group_fights(timeline)
    containing = [fight for fight in clusters if any(kill is event or kill == event for kill in fight)]
    cluster = containing[0] if len(containing) == 1 else [event]
    bounded = [kill for kill in cluster if start <= kill["timestamp"] <= min(end, timeline["duration"])]
    window_kills = [
        kill for kill in timeline["events"] if kill["type"] == "CHAMPION_KILL" and start <= kill["timestamp"] <= end
    ]
    other_kills = [kill for kill in window_kills if kill not in bounded]
    overlapping = any(kill.get("victim_id") == player_id for kill in window_kills if kill != event)
    nearby_other_cluster = any(
        kill not in cluster
        and (
            position_distance(event.get("position"), kill.get("position")) is None
            or position_distance(event.get("position"), kill.get("position")) <= FIGHT_POSITION_DISTANCE
        )
        for kill in other_kills
    )
    summary = kill_exchange_summary(bounded, player_id, match, timestamp)
    objective = death_objective_context(timestamp, timeline, match, own, enemy)
    coverage = event_window_coverage(timeline, start, end)
    reasons = []
    if not coverage["complete"] or not objective["coverage"]["complete"]:
        reasons.append("incomplete_event_window_coverage")
    if overlapping or nearby_other_cluster or len(containing) > 1:
        reasons.append("overlapping_deaths_or_uncertain_cluster_assignment")
    if len(bounded) != len(cluster):
        reasons.append("kill_cluster_extends_beyond_death_window")
    if not summary["kill_attribution_complete"] or summary["player_deaths"] != 1:
        reasons.append("unclear_kill_attribution")
    if objective["enemy_objective_followup"] is None or objective["allied_objective_followup"] is None:
        reasons.append("unknown_objective_attribution_or_coverage")
    difference = summary["team_kill_differential"]
    if (difference > 0 and objective["enemy_objective_followup"]) or (
        difference < 0 and objective["allied_objective_followup"]
    ):
        reasons.append("kill_trade_and_objective_followup_have_conflicting_values")
    if objective["enemy_objective_followup"] and objective["allied_objective_followup"]:
        reasons.append("both_teams_captured_objectives; relative_value_not_established")
    classification = "unclear"
    if not reasons:
        if difference > 0 or (difference == 0 and objective["allied_objective_followup"]):
            classification = "favorable"
        elif difference < 0 or objective["enemy_objective_followup"]:
            classification = "unfavorable"
        else:
            classification = "even"
    signals = []
    if classification != "unclear":
        signals.append(
            {
                "favorable": "favorable_death_exchange",
                "unfavorable": "unfavorable_death_exchange",
                "even": "neutral_trade_death",
            }[classification]
        )
    if summary["player_kills_by_timing"]["before"] >= 2:
        signals.append("multiple_kills_before_death")
    if summary["enemy_kills"] == 1 and summary["allied_kills"] in {1, 2, 3}:
        signals.append(f"traded_1_for_{summary['allied_kills']}")
    enemy_roles = {death["role"] for death in summary["enemy_champions_killed"]}
    for role, name in (("JUNGLE", "enemy_jungler_killed_in_exchange"), ("UTILITY", "enemy_support_killed_in_exchange")):
        if role in enemy_roles:
            signals.append(name)
    if enemy_roles & {"BOTTOM", "MIDDLE"}:
        signals.append("enemy_bottom_or_middle_killed_in_exchange")
    if objective["enemy_objective_followup"] is True:
        signals.append("enemy_objective_after_death")
    elif objective["enemy_objective_followup"] is False:
        signals.append("no_enemy_objective_followup")
    if objective["allied_objective_followup"] is True:
        signals.append("allied_objective_followup")
    cluster_summary = kill_exchange_summary(cluster, player_id, match, timestamp)
    return {
        "death_outcome": {
            "timestamp": timestamp,
            "window_before_ms": DEATH_OUTCOME_BEFORE_MS,
            "window_after_ms": DEATH_OUTCOME_AFTER_MS,
            "coverage": coverage,
            **summary,
            "objective_context": objective,
            "outcome_classification": classification,
            "classification_basis": "bounded_cluster_kill_trade_and_temporal_objective_followup",
            "uncertainties": reasons,
            "signals": signals,
            "signals_valence": "observation",
            "other_kills_in_time_window": [
                {"timestamp": kill["timestamp"], "victim_id": kill.get("victim_id")} for kill in other_kills
            ],
            "interpretation": "observable_outcome_only; does_not_establish_decision_quality_or_optimality",
            "overlap_note": "each_death_is_independent; windows_may_share_events; do_not_sum_exchange_kills_across_deaths",
        },
        "fight_context": {
            "fight_id": fight_cluster_id(cluster) if containing else None,
            "player_participated": True,
            "start_timestamp": cluster[0]["timestamp"],
            "end_timestamp": cluster[-1]["timestamp"],
            "player_kills": cluster_summary["player_kills"],
            "player_assists": cluster_summary["player_assists"],
            "allied_kills": cluster_summary["allied_kills"],
            "enemy_kills": cluster_summary["enemy_kills"],
            "kill_differential": cluster_summary["team_kill_differential"],
            "interpretation": "approximate_kill_cluster_not_complete_teamfight; may_extend_beyond_death_window",
        },
        "death_location_context": death_location_context(event, timeline, match, own),
    }


def analyze_death(event: dict, parsed_timeline: dict, parsed_match: dict) -> dict:
    """
    Build a death report from combat evidence and sampled context.
    """
    frames = parsed_timeline["frames"]
    player_id = parsed_timeline["player_id"]
    participant_teams = parsed_match["participant_teams"]
    participant_info = parsed_match["participant_info"]
    player_team = participant_teams[player_id]
    enemy_team = None

    for team_id in set(participant_teams.values()):
        if team_id != player_team:
            enemy_team = team_id
            break
    death_timestamp = event["timestamp"]
    before = find_frame_before(frames, death_timestamp - 1)
    later = find_frame_before(frames, death_timestamp + CONVERSION_WINDOW)
    killer_id = event["killer_id"]
    attacker_ids = {killer_id, *event.get("assist_ids", [])}

    for source in annotate_damage_sources(event.get("damage_sources", []), parsed_match, player_team):
        if source["resolved_team_relation"] != "enemy":
            continue
        attacker_ids.add(source["participant_id"])
    attacker_ids.discard(0)
    attacker_ids.discard(None)

    attackers = []

    for attacker_id in sorted(attacker_ids):
        if participant_teams.get(attacker_id) != enemy_team:
            continue
        info = participant_info.get(attacker_id, {})

        attackers.append({"participant_id": attacker_id, "champion": info.get("champion"), "role": info.get("role")})
    jungler_involved = any(attacker["role"] == "JUNGLE" for attacker in attackers)
    damage_sources = annotate_damage_sources(event.get("damage_sources", []), parsed_match, player_team)
    ability_hits = [source for source in damage_sources if not source["basic"] and source["spell_name"]]
    health_ratio_before = None

    if before is not None:
        health = before["player"]["health"]
        max_health = before["player"]["max_health"]

        if health is not None and max_health and max_health > 0:
            health_ratio_before = health / max_health
    killer_level_advantage = None
    killer_spent_gold_advantage = None

    if before is not None:
        killer_state = before["participants"].get(killer_id)

        if killer_state is not None:
            killer_level_advantage = killer_state["level"] - before["player"]["level"]
            player_spent = before["player"]["total_gold"] - before["player"]["current_gold"]
            killer_spent = killer_state["total_gold"] - killer_state["current_gold"]
            killer_spent_gold_advantage = killer_spent - player_spent
    team_gold_change = None

    if before is not None and later is not None and later["timestamp"] > before["timestamp"]:
        before_team = get_team_state(before, player_team, enemy_team, participant_teams)
        later_team = get_team_state(later, player_team, enemy_team, participant_teams)
        team_gold_change = later_team["team_gold_diff"] - before_team["team_gold_diff"]
    follow_events = get_events_between(parsed_timeline["events"], death_timestamp, death_timestamp + CONVERSION_WINDOW)
    team_kills_after = 0
    enemy_kills_after = 0
    objectives_after = []
    structures_after = []

    for follow_event in follow_events:
        event_team = get_event_team(follow_event, participant_teams)

        if follow_event["type"] == "CHAMPION_KILL":
            if event_team == player_team:
                team_kills_after += 1
            elif event_team == enemy_team:
                enemy_kills_after += 1
        elif follow_event["type"] == "ELITE_MONSTER_KILL":
            objectives_after.append(
                {
                    "timestamp": follow_event["timestamp"],
                    "team_id": event_team,
                    "monster": follow_event.get("monster_type"),
                    "sub_type": follow_event.get("monster_sub_type"),
                }
            )
        elif follow_event["type"] == "BUILDING_KILL":
            structures_after.append(
                {
                    "timestamp": follow_event["timestamp"],
                    "building_type": follow_event.get("building_type"),
                    "team_id": event_team,
                    "tower_type": follow_event.get("tower_type"),
                    "lane": follow_event.get("lane"),
                }
            )
    result = {
        "time": event["time"],
        "timestamp": death_timestamp,
        "position": event["position"],
        "killer_id": killer_id,
        "killer_champion": (participant_info.get(killer_id, {}).get("champion")),
        "killer_role": (participant_info.get(killer_id, {}).get("role")),
        "attackers": attackers,
        "attacker_count": len(attackers),
        "jungler_involved": (jungler_involved),
        "nearby_allies": None,
        "nearby_enemies": None,
        "health_ratio_before": (health_ratio_before),
        "killer_level_advantage": (killer_level_advantage),
        "killer_spent_gold_advantage": (killer_spent_gold_advantage),
        "ability_hits": ability_hits,
        "important_spell_hits": [],
        "damage_sources": damage_sources,
        "assist_ids": event.get("assist_ids", []),
        "team_outcome_after": {
            "team_gold_diff_change": (team_gold_change),
            "team_kills": (team_kills_after),
            "enemy_kills": (enemy_kills_after),
            "objectives": (objectives_after),
            "structures": (structures_after),
        },
    }
    state_age = death_timestamp - before["timestamp"] if before else None
    prior = find_frame_before(frames, before["timestamp"] - 1) if before else None
    result["evidence_quality"] = {
        "combat": "event_record",
        "position": "coarse_pre_death_snapshot",
        "position_age_ms": state_age,
        "state_age_ms": state_age,
        "wave_state": "unobserved",
        "threat_semantics": "deferred_to_coaching_layer",
    }
    result["state_before_death"] = dict(before["player"]) if before else None
    if before:
        result["state_before_death"]["sample_timestamp"] = before["timestamp"]
        result["state_before_death"]["sample_age_ms"] = state_age
        result["state_before_death"]["interpretation"] = "historical_snapshot_only; not_fight_entry_state"
        result["state_before_death"]["approximate_spent_gold"] = (
            before["player"]["total_gold"] - before["player"]["current_gold"]
        )
    earlier_deaths = [
        e["timestamp"]
        for e in parsed_timeline["events"]
        if e["type"] == "CHAMPION_KILL" and e["victim_id"] == player_id and e["timestamp"] < death_timestamp
    ]
    previous_death = max(earlier_deaths, default=None)
    invalid_snapshot = before is not None and (
        before["player"].get("alive") is False or (previous_death is not None and before["timestamp"] <= previous_death)
    )
    result["encounter_context_status"] = "sampled_context_available" if before else "no_snapshot"
    if invalid_snapshot:
        result["encounter_context_status"] = (
            "sampled_dead_following_earlier_death"
            if before["player"].get("alive") is False and previous_death is not None
            else "snapshot_not_valid_for_current_life"
        )
        result["historical_snapshot"] = result["state_before_death"]
        result["historical_snapshot"]["sample_status"] = "not_valid_for_current_life"
        result["state_before_death"] = None
        result["health_ratio_before"] = None
        result["nearby_allies"] = None
        result["nearby_enemies"] = None
        result["two_samples_without_allies"] = False
        result["killer_level_advantage"] = None
        result["killer_spent_gold_advantage"] = None
        result["evidence_quality"]["position"] = "unavailable_for_current_encounter"
    proximity = death_proximity_snapshot(before, death_timestamp, player_id, parsed_match, not invalid_snapshot)
    result["proximity_snapshot"] = proximity
    result["nearby_allies"] = proximity["allies"]
    result["nearby_enemies"] = proximity["enemies"]
    result["evidence_quality"]["position"] = proximity["status"]
    prior_valid = previous_death is None or (prior is not None and prior["timestamp"] > previous_death)
    prior_proximity = death_proximity_snapshot(prior, death_timestamp, player_id, parsed_match, prior_valid)
    samples_available = proximity["allies"] is not None and prior_proximity["allies"] is not None
    result["two_samples_without_allies"] = (
        proximity["allies"] == [] and prior_proximity["allies"] == [] if samples_available else None
    )
    result["two_samples_without_allies_semantics"] = "historical_snapshots_only; not_death_time_isolation"
    state = result["state_before_death"]
    if state:
        state["sample_status"] = "observed_historical_snapshot" if state_age <= MAX_STATE_AGE else "stale_historical_snapshot"
    result["death_evidence_version"] = 3
    result["unknowns"] = [
        "fight_entry_health", "fight_start_and_duration", "ally_protection_during_fight", "spell_availability",
        "safe_recall_opportunity", "escape_opportunity", "death_time_isolation", "death_time_ally_distance",
        "player_intent", "damage_cast_count", "damage_sequence_and_initiation",
    ]
    result["damage_evidence_semantics"] = (
        "recorded_damage_involvement_only; does_not_establish_initiation_or_cause; "
        "grouped_totals_may_include_multiple_hits_or_casts; event_timestamp_is_not_cast_time"
    )
    result["personal_outcome"] = {"death": True, "decision_quality": "not_determined"}
    result["team_outcome_after"].update(
        {
            "causality": "not_established",
            "requested_window_ms": CONVERSION_WINDOW,
            "observed_end_timestamp": min(death_timestamp + CONVERSION_WINDOW, parsed_timeline["duration"]),
            "gold_sample_start": before["timestamp"] if before else None,
            "gold_sample_end": later["timestamp"] if later else None,
        }
    )
    result["team_outcome_after"].update(
        outcome_window_metadata(death_timestamp, parsed_timeline["duration"], before, later)
    )
    result["game_state_before"] = game_state_at(death_timestamp - 1, parsed_timeline, parsed_match)
    result["recent_events"] = [
        compact_event(e)
        for e in get_events_between(parsed_timeline["events"], death_timestamp - MAX_STATE_AGE, death_timestamp - 1)
        if e["type"] in {"CHAMPION_KILL", "ELITE_MONSTER_KILL", "BUILDING_KILL"} or e.get("participant_id") == player_id
    ]
    result["recent_ward_events"] = [
        compact_event(e)
        for e in get_events_between(parsed_timeline["events"], death_timestamp - RECENT_DEATH_LOOKBACK, death_timestamp)
        if e["type"] in {"WARD_PLACED", "WARD_KILL"}
    ]
    result["unspent_gold_context"] = unspent_gold_context(parsed_match["player"]["role"], result["state_before_death"])
    result.update(build_death_outcome(event, parsed_timeline, parsed_match))
    result["cause_candidates"] = create_death_cause_candidates(result)
    result["cause_candidate_status"] = (
        "historical_observations_present; causes_not_established"
        if result["cause_candidates"]
        else "insufficient_evidence_for_configured_rules; not_a_no_mistake_verdict"
    )

    return result


def analyze_deaths(parsed_timeline: dict, parsed_match: dict) -> list[dict]:
    """
    Analyze each observed player death.
    """
    player_id = parsed_timeline["player_id"]
    results = []

    for event in parsed_timeline["events"]:
        if event["type"] != "CHAMPION_KILL":
            continue
        if event["victim_id"] != player_id:
            continue
        results.append(analyze_death(event, parsed_timeline, parsed_match))
    return results


def kills_are_same_fight(previous: dict, current: dict) -> bool:
    """
    Check whether kill events are close enough in time and position to group.
    """
    time_gap = current["timestamp"] - previous["timestamp"]

    if time_gap > FIGHT_EVENT_GAP:
        return False
    distance = position_distance(previous.get("position"), current.get("position"))

    if distance is None:
        previous_ids = {previous.get("killer_id"), *previous.get("assist_ids", [])} - {0, None}
        current_ids = {current.get("killer_id"), *current.get("assist_ids", [])} - {0, None}
        return bool(previous_ids & current_ids)
    return distance <= FIGHT_POSITION_DISTANCE


def group_fights(parsed_timeline: dict) -> list[list[dict]]:
    """
    Keep spatial clusters active despite interleaved kills elsewhere on the map.
    """
    fights = []
    kills = sorted((e for e in parsed_timeline["events"] if e["type"] == "CHAMPION_KILL"), key=lambda e: e["timestamp"])
    for kill in kills:
        candidates = [
            fight
            for fight in fights
            if kills_are_same_fight(fight[-1], kill)
            and (position_distance(fight[0].get("position"), kill.get("position")) or 0) <= FIGHT_POSITION_DISTANCE
        ]
        if candidates:
            min(
                candidates,
                key=lambda f: position_distance(f[-1].get("position"), kill.get("position")) or FIGHT_POSITION_DISTANCE,
            ).append(kill)
        else:
            fights.append([kill])
    return [fight for fight in fights if len(fight) >= 2]


def fight_participant_evidence(fight: list[dict], match: dict) -> list[dict]:
    """
    Collect participant involvement evidence for a fight.
    """
    evidence = {}
    for kill in fight:
        for kind, ids in [
            ("killer", [kill.get("killer_id")]),
            ("victim", [kill.get("victim_id")]),
            ("credited_assist", kill.get("assist_ids", [])),
        ]:
            for pid in ids:
                if pid in match["participant_teams"]:
                    evidence.setdefault(pid, set()).add(kind)
        victim_team = match["participant_teams"].get(kill.get("victim_id"))
        for source in annotate_damage_sources(kill.get("damage_sources", []), match, victim_team):
            pid = source["resolved_participant_id"]
            if pid is not None and source["resolved_team_relation"] == "enemy":
                evidence.setdefault(pid, set()).add("reported_damage")
    return [{"participant_id": pid, "evidence_types": sorted(kinds)} for pid, kinds in sorted(evidence.items())]


def analyze_fight(fight: list[dict], parsed_timeline: dict, parsed_match: dict) -> dict:
    """
    Summarize a fight and its observed follow-up events.
    """
    participant_teams = parsed_match["participant_teams"]
    player_id = parsed_timeline["player_id"]
    player_team = participant_teams[player_id]
    enemy_team = None

    for team_id in set(participant_teams.values()):
        if team_id != player_team:
            enemy_team = team_id
            break
    player_team_kills = 0
    enemy_team_kills = 0
    player_involved = False
    player_died = False

    for kill in fight:
        killer_team = participant_teams.get(kill["killer_id"])

        if killer_team == player_team:
            player_team_kills += 1
        elif killer_team == enemy_team:
            enemy_team_kills += 1
        if get_player_combat_result(kill, player_id) is not None:
            player_involved = True
        if kill["victim_id"] == player_id:
            player_died = True
    start_timestamp = fight[0]["timestamp"]
    end_timestamp = fight[-1]["timestamp"]
    conversions = get_events_between(parsed_timeline["events"], end_timestamp, end_timestamp + CONVERSION_WINDOW)
    objectives = []
    structures = []

    for event in conversions:
        event_team = get_event_team(event, participant_teams)

        if event["type"] == "ELITE_MONSTER_KILL":
            objectives.append(
                {
                    "timestamp": event["timestamp"],
                    "team_id": event_team,
                    "monster": event.get("monster_type"),
                    "sub_type": event.get("monster_sub_type"),
                }
            )
        elif event["type"] == "BUILDING_KILL":
            structures.append(
                {
                    "timestamp": event["timestamp"],
                    "building_type": event.get("building_type"),
                    "team_id": event_team,
                    "tower_type": event.get("tower_type"),
                    "lane": event.get("lane"),
                }
            )
    return {
        "player_team_id": player_team,
        "game_phase": game_state_at(start_timestamp, parsed_timeline, parsed_match)["phase"]["label"],
        "participants": [p["participant_id"] for p in fight_participant_evidence(fight, parsed_match)],
        "participant_evidence": fight_participant_evidence(fight, parsed_match),
        "approximate_location": fight[0].get("position"),
        "fight_id": fight_cluster_id(fight),
        "timing_basis": "first_to_last_observed_kill_not_full_combat_duration",
        "kill_differential": player_team_kills - enemy_team_kills,
        "conversion_window_seconds": CONVERSION_WINDOW // 1000,
        "conversion_observed_seconds": max(0, min(CONVERSION_WINDOW, parsed_timeline["duration"] - end_timestamp))
        / 1000,
        "conversion_causality": "not_established; overlapping_windows_may_share_events",
        "start_time": fight[0]["time"],
        "end_time": fight[-1]["time"],
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "player_team_kills": (player_team_kills),
        "enemy_team_kills": (enemy_team_kills),
        "player_involved": player_involved,
        "player_died": player_died,
        "objectives_after": objectives,
        "structures_after": structures,
    }


def analyze_fights(parsed_timeline: dict, parsed_match: dict) -> list[dict]:
    """
    Analyze grouped kill events involving the player.
    """
    fights = group_fights(parsed_timeline)

    return [analyze_fight(fight, parsed_timeline, parsed_match) for fight in fights]


def build_coaching_signals(cs_analysis: dict, deaths: list[dict], farm_windows: list[dict],
                           fights: list[dict]) -> list[dict]:
    """
    Build evidence-backed review signals from the game analysis.
    """
    signals = []
    types = {cause["type"] for death in deaths for cause in death["cause_candidates"]}
    for kind in sorted(types):
        matching = [death for death in deaths if any(c["type"] == kind for c in death["cause_candidates"])]
        if len(matching) >= 2:
            signals.append(
                {
                    "type": "repeated_" + kind,
                    "kind": "derived_observation",
                    "valence": "observation",
                    "interpretation": "recurring_snapshot_observations; cause_and_decision_quality_not_established",
                    "evidence": {"death_timestamps": [d["timestamp"] for d in matching]},
                }
            )
    jungle_deaths = [d for d in deaths if d["jungler_involved"]]
    if len(jungle_deaths) >= 2:
        signals.append(
            {
                "type": "repeated_enemy_jungler_involvement",
                "kind": "derived_metric",
                "valence": "observation",
                "evidence": {"death_timestamps": [d["timestamp"] for d in jungle_deaths]},
                "interpretation": "does_not_establish_tracking_error",
            }
        )
    unexplained = [w for w in farm_windows if w["classification"]["reason"] == "unexplained_low_farm"]
    if len(unexplained) >= 2:
        signals.append(
            {
                "type": "possible_repeated_unexplained_farm_drop",
                "confidence": 0.5,
                "evidence": [{"start": w["start_time"], "end": w["end_time"]} for w in unexplained],
                "availability": "unknown",
            }
        )
    for window in farm_windows:
        if window["classification"]["reason"] == "possible_teammate_wave_absorption":
            signals.append({"type": "possible_teammate_wave_absorption", "confidence": 0.5, "evidence": window})
    for fight in fights:
        if not fight["player_involved"] or fight["kill_differential"] < 2:
            continue
        converted = any(
            e["team_id"] == fight["player_team_id"] for e in fight["objectives_after"] + fight["structures_after"]
        )
        if not converted and fight["conversion_observed_seconds"] >= CONVERSION_WINDOW / 1000:
            signals.append(
                {
                    "type": "fight_conversion_review_candidate",
                    "confidence": 0.5,
                    "evidence": {
                        "fight_start": fight["start_timestamp"],
                        "kill_differential": fight["kill_differential"],
                        "allied_objectives_or_structures_after": 0,
                    },
                    "safe_objective_availability": "unknown",
                }
            )
    return signals


def find_major_swings(windows: list[dict]) -> list[dict]:
    """
    Identify windows with large matchup or team gold changes.
    """
    results = []

    for window in windows:
        matchup = abs(window["matchup_gold_diff_change"] or 0)
        team = abs(window["team_gold_diff_change"])

        if matchup >= MAJOR_MATCHUP_GOLD_SWING or team >= MAJOR_TEAM_GOLD_SWING:
            results.append(window)
    return results


def analyze_resource_events(timeline: dict, match: dict) -> list[dict]:
    """
    Observed captures and plates, with no assumption of free availability.
    """
    results = []
    for event in timeline["events"]:
        if event["type"] not in {"ELITE_MONSTER_KILL", "TURRET_PLATE_DESTROYED", "BUILDING_KILL"}:
            continue
        sample = find_frame_before(timeline["frames"], event["timestamp"] - 1)
        player_id = timeline["player_id"]
        results.append(
            {
                **compact_event(event),
                "gaining_team_id": get_event_team(event, match["participant_teams"]),
                "player_recorded_participation": event.get("killer_id") == player_id
                or player_id in event.get("assist_ids", []),
                "participation_note": "absence_from_event_does_not_prove_absence_from_objective",
                "sample_timestamp": sample["timestamp"] if sample else None,
                "sampled_alive": (
                    {pid: state["alive"] for pid, state in sample["participants"].items()} if sample else {}
                ),
                "recent_kill_timestamps": [
                    e["timestamp"]
                    for e in get_events_between(
                        timeline["events"], event["timestamp"] - FIGHT_EVENT_GAP, event["timestamp"]
                    )
                    if e["type"] == "CHAMPION_KILL"
                    and position_distance(e.get("position"), event.get("position")) is not None
                    and position_distance(e.get("position"), event.get("position")) <= FIGHT_POSITION_DISTANCE
                ],
            }
        )
    return results


def build_aggregation_evidence(game: dict) -> dict:
    """
    Stable measurements and occurrences for consumers without raw timelines.
    """
    cs = game["cs_analysis"]
    metrics = {
        key: cs.get(key)
        for key in (
            "overall_cs_per_min",
            "lane_cs_per_wave",
            "post_lane_cs_per_min",
            "matchup_cs_diff_at_10",
            "matchup_gold_diff_at_10",
            "matchup_xp_diff_at_10",
        )
    }
    metrics.update(
        deaths=game["player"]["deaths"],
        observed_deaths=len(game["deaths"]),
        enemy_jungler_deaths=0,
        possible_isolation_deaths=None,
        possible_low_health_exposure_deaths=0,
        limited_allied_proximity_in_last_snapshot_deaths=0,
        low_sampled_health_deaths=0,
        favorable_death_exchanges=0,
        unfavorable_death_exchanges=0,
        even_death_exchanges=0,
        unclear_death_exchanges=0,
        reliable_ally_proximity_samples=0,
        sampled_health_death_samples=0,
        large_unspent_gold_deaths=0,
        spent_gold_disadvantage_deaths=0,
        level_disadvantage_deaths=0,
        fresh_death_state_samples=0,
        engage_cc_deaths=None,
        unexplained_low_farm_windows=0,
        teammate_absorption_windows=0,
    )
    occurrences = []

    def add(kind: str, timestamp: int | None, phase: str, evidence: dict, confidence: float | None = None,
            valence: str = "observation") -> None:
        """
        Append an aggregation occurrence with its evidence and confidence.
        """
        item = {
            "type": kind,
            "timestamp": timestamp,
            "game_phase": phase,
            "champion": game["player"]["champion"],
            "role": game["player"]["role"],
            "kind": "inference" if confidence is not None else "derived_metric",
            "valence": valence,
            "evidence": evidence,
        }
        if confidence is not None:
            item["confidence"] = confidence
        occurrences.append(item)

    for death in game["deaths"]:
        phase = death["game_state_before"]["phase"]["label"]
        metrics["reliable_ally_proximity_samples"] += int(death["nearby_allies"] is not None)
        if death["jungler_involved"]:
            metrics["enemy_jungler_deaths"] += 1
            add(
                "enemy_jungler_involved_in_death",
                death["timestamp"],
                phase,
                {"attacker_ids": [a["participant_id"] for a in death["attackers"]]},
            )
        for cause in death["cause_candidates"]:
            kind = cause["type"]
            if kind + "_deaths" in metrics and kind != "large_unspent_gold":
                metrics[kind + "_deaths"] += 1
            if kind == "low_sampled_health":
                metrics["possible_low_health_exposure_deaths"] += 1  # Compatibility alias for a sampled measurement.
            add(kind, death["timestamp"], phase, cause.get("evidence", {}), valence="observation")
            occurrences[-1]["interpretation"] = cause["interpretation"]
        state = death.get("state_before_death")
        age = death["evidence_quality"].get("state_age_ms")
        if state and age is not None and age <= MAX_STATE_AGE:
            metrics["fresh_death_state_samples"] += 1
            metrics["sampled_health_death_samples"] += int(death["health_ratio_before"] is not None)
            for metric, condition in (
                ("large_unspent_gold_deaths", state["current_gold"] >= HIGH_UNSPENT_GOLD
                 and not death["unspent_gold_context"]["suppress_unspent_gold_coaching"]),
                ("spent_gold_disadvantage_deaths", (death["killer_spent_gold_advantage"] or 0) > 0),
                ("level_disadvantage_deaths", (death["killer_level_advantage"] or 0) > 0),
            ):
                metrics[metric] += int(condition)
        outcome = death.get("death_outcome")
        if outcome:
            metrics[outcome["outcome_classification"] + "_death_exchanges"] += 1
            for signal in outcome["signals"]:
                add(signal, death["timestamp"], phase, {
                    "outcome_classification": outcome["outcome_classification"],
                    "player_kills": outcome["player_kills"], "player_assists": outcome["player_assists"],
                    "allied_kills": outcome["allied_kills"], "enemy_kills": outcome["enemy_kills"],
                    "team_kill_differential": outcome["team_kill_differential"],
                    "fight_id": death["fight_context"]["fight_id"],
                    "objective_followup": {key: outcome["objective_context"][key] for key in
                                           ("enemy_objective_followup", "allied_objective_followup", "window_after_ms")},
                    "interpretation": "observable_outcome_only; does_not_establish_decision_quality_or_prevention",
                })
    if game["deaths"] and not metrics["reliable_ally_proximity_samples"]:
        metrics["limited_allied_proximity_in_last_snapshot_deaths"] = None
    if game["deaths"] and not metrics["sampled_health_death_samples"]:
        metrics["low_sampled_health_deaths"] = None
        metrics["possible_low_health_exposure_deaths"] = None
    for window in game["farm_windows"]:
        classification = window["classification"]
        reason = classification["reason"]
        metric = {
            "unexplained_low_farm": "unexplained_low_farm_windows",
            "possible_teammate_wave_absorption": "teammate_absorption_windows",
        }.get(reason)
        if metric:
            metrics[metric] += 1
            add(
                reason,
                window["start_timestamp"],
                window["game_phase"],
                {"start_time": window["start_time"], "end_time": window["end_time"]},
                classification.get("confidence", 0.5),
                "weakness_candidate" if reason == "unexplained_low_farm" else "observation",
            )
    participating = [fight for fight in game["fights"] if fight["player_involved"]]
    metrics.update(
        observed_fights=len(game["fights"]),
        participating_fights=len(participating),
        fight_deaths=sum(f["player_died"] for f in participating),
        positive_kill_fights=sum(f["kill_differential"] > 0 for f in participating),
        negative_kill_fights=sum(f["kill_differential"] < 0 for f in participating),
        converted_positive_fights=0,
    )
    for fight in participating:
        captures = [
            e
            for e in fight["objectives_after"] + fight["structures_after"]
            if e["team_id"] == game["player"]["team_id"]
        ]
        if fight["kill_differential"] > 0 and captures:
            metrics["converted_positive_fights"] += 1
            add(
                "favorable_fight_followed_by_allied_capture",
                fight["start_timestamp"],
                fight["game_phase"],
                {
                    "kill_differential": fight["kill_differential"],
                    "capture_timestamps": [e["timestamp"] for e in captures],
                    "causality": "not_established",
                },
                valence="strength_candidate",
            )
    objectives = [e for e in game["resource_events"] if e["type"] == "ELITE_MONSTER_KILL"]
    metrics.update(
        observed_objectives=len(objectives),
        recorded_objective_participations=sum(e["player_recorded_participation"] for e in objectives),
        major_economic_swings=len(game["major_swings"]),
        possible_resource_misses=None,
    )  # Availability has not been established.
    if game["queue_id"] == 480:
        for key in ("unexplained_low_farm_windows", "teammate_absorption_windows", "major_economic_swings"):
            metrics[key] = None  # Uncalibrated measurements are unavailable, not observed zeroes.
    death_context = {"phase": {}, "killer_role": {}}
    for death in game["deaths"]:
        for key, value in (
            ("phase", death["game_state_before"]["phase"]["label"]),
            ("killer_role", death.get("killer_role") or "UNKNOWN"),
        ):
            death_context[key][value] = death_context[key].get(value, 0) + 1
    if not game["timeline_observation_available"]:
        summary_keys = {"overall_cs_per_min", "deaths"}
        metrics = {key: value if key in summary_keys else None for key, value in metrics.items()}
    return {
        "aggregate_metrics": metrics,
        "pattern_occurrences": occurrences,
        "death_context_counts": death_context,
        "strength_signals": [o for o in occurrences if o["valence"] == "strength_candidate"],
        "weakness_signals": [o for o in occurrences if o["valence"] == "weakness_candidate"],
        "measurement_availability": {
            "engage_cc": "no_audited_threat_metadata",
            "resource_opportunities": "availability_not_established",
            "possible_isolation_deaths": "unavailable; historical_proximity_does_not_establish_isolation",
            "possible_low_health_exposure_deaths": "alias_for_low_sampled_health_deaths; not_fight_entry_health",
            "death_causes": "not_established; cause_candidates_contains_neutral_observations",
        },
    }


def analyze_game(parsed_timeline: dict, parsed_match: dict, *, include_windows: bool = False) -> dict:
    """
    Build a deterministic game report from parsed match and timeline data.
    """
    require_supported_analysis_match({"info": {"queueId": parsed_match.get("queue_id")}})
    swiftplay = parsed_match["queue_id"] == 480
    windows = create_windows(parsed_timeline, parsed_match)
    cs_analysis = analyze_cs(parsed_timeline, parsed_match)
    farm_windows = [] if swiftplay else analyze_farm_windows(windows, parsed_timeline, parsed_match)
    deaths = analyze_deaths(parsed_timeline, parsed_match)
    fights = analyze_fights(parsed_timeline, parsed_match)
    coaching_signals = build_coaching_signals(cs_analysis, deaths, farm_windows, fights)
    result = {
        "schema_version": 2,
        "analysis_version": ANALYSIS_VERSION,
        "death_evidence_version": 3,
        "timeline_observation_available": len(parsed_timeline["frames"]) >= 2,
        "match_id": parsed_match["match_id"],
        "puuid": parsed_match["player"]["puuid"],
        "game_start_timestamp": parsed_match.get("game_start_timestamp"),
        "duration_seconds": parsed_match["game_duration"],
        "game_version": parsed_match["game_version"],
        "queue_id": parsed_match["queue_id"],
        "queue_name": SUPPORTED_ANALYSIS_QUEUES[parsed_match["queue_id"]],
        "player": {
            **parsed_match["player"],
            "team_id": parsed_match["participant_teams"][parsed_timeline["player_id"]],
        },
        "game_context": game_state_at(parsed_timeline["duration"], parsed_timeline, parsed_match),
        "cs_analysis": cs_analysis,
        "major_swings": [] if swiftplay else find_major_swings(windows),
        "farm_windows": farm_windows,
        "deaths": deaths,
        "fights": fights,
        "coaching_signals": (coaching_signals),
        "resource_events": analyze_resource_events(parsed_timeline, parsed_match),
        "resource_opportunities": [],
        "resource_opportunity_status": "availability_not_established; see_farm_review_and_observed_resource_events",
        "limitations": list(LIMITATIONS) + ([SWIFTPLAY_LIMITATION] if swiftplay else []),
    }
    result["major_swings"] = [compact_window(w) for w in result["major_swings"]]
    result.update(build_aggregation_evidence(result))
    if include_windows:
        result["windows"] = windows
    return result


def print_death_summary(death: dict) -> None:
    """
    Print a readable summary of a death and its evidence.
    """
    state = death.get("state_before_death") or {}
    quality = death["evidence_quality"]
    outcome = death["team_outcome_after"]
    print(f"\n{death['time']} | Killed by {death['killer_champion']}")
    print("Combat contributors from event:", death["attackers"])
    print("Encounter context:", death["encounter_context_status"])
    if death.get("historical_snapshot"):
        print("Historical snapshot (not current encounter state):", death["historical_snapshot"])
    print(
        "Pre-death snapshot timestamp (ms):", state.get("sample_timestamp"), "| age (ms):", quality["position_age_ms"]
    )
    print("Proximity semantics:", death.get("proximity_snapshot", {}).get("interpretation", "historical_only"))
    print("Sampled nearby allies:", death["nearby_allies"] if death["nearby_allies"] is not None else "unavailable")
    print("Sampled nearby enemies:", death["nearby_enemies"] if death["nearby_enemies"] is not None else "unavailable")
    print("Sampled absence does not override combat event involvement.")
    print(
        "Sampled health ratio:",
        death["health_ratio_before"],
        "| level:",
        state.get("level"),
        "| unspent gold:",
        state.get("current_gold"),
        "| approximate spent gold:",
        state.get("approximate_spent_gold"),
    )
    print(
        "Killer sampled level advantage:",
        death["killer_level_advantage"],
        "| approximate spent-gold advantage:",
        death["killer_spent_gold_advantage"],
    )
    print("Observable death outcome:", death.get("death_outcome", "unavailable"))
    print("Gold-coaching context:", death.get("unspent_gold_context", "unavailable"))
    print("Reported ability/effect evidence:", death["ability_hits"])
    print("Historical observations (not death causes):", death["cause_candidates"])
    print("Unknown encounter details:", death.get("unknowns", []))
    print("Candidate status:", death["cause_candidate_status"])
    print(
        "Events after death:",
        {key: outcome[key] for key in ("event_window", "team_kills", "enemy_kills", "objectives", "structures")},
    )
    print("Separate sampled team gold change:", outcome["team_gold_diff_change"], outcome["gold_window"])
    print(outcome["window_comparison"], "| causality:", outcome["causality"])


if __name__ == "__main__":
    from app.player_data.riot_api import get_account_by_riot_id, get_recent_match_ids, get_match, get_match_timeline

    account = get_account_by_riot_id(game_name="Cessereendya", tag_line="7944")
    puuid = account["puuid"]
    match_ids = get_recent_match_ids(puuid=puuid, count=3)

    if not match_ids:
        raise ValueError("No recent matches found.")
    match_id = match_ids[min(2, len(match_ids) - 1)]
    match = get_match(match_id)
    from app.player_data.analysis_service import require_current_season

    require_current_season(match)
    require_supported_analysis_match(match)
    parsed_match = parse_match(match, puuid)
    player_id = parsed_match["player"]["participant_id"]
    opponent_id = parsed_match["opponent"]["participant_id"] if parsed_match["opponent"] else None
    timeline = get_match_timeline(match_id)
    parsed_timeline = parse_timeline(timeline, player_id, opponent_id)
    analysis = analyze_game(parsed_timeline, parsed_match)

    print()
    print("CS ANALYSIS")
    print(analysis["cs_analysis"])

    print()
    print("DEATH ANALYSIS")

    for death in analysis["deaths"]:
        print_death_summary(death)
    print()
    print("FARM REVIEW")

    for farm_window in analysis["farm_windows"]:
        print(farm_window)
    print()
    print("FIGHTS")

    for fight in analysis["fights"]:
        if fight["player_involved"]:
            print(fight)
    print()
    print("COACHING SIGNALS")

    for signal in analysis["coaching_signals"]:
        print(signal)
