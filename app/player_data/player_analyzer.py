"""Aggregate versioned game analyses only. No network or raw Riot parsing."""

from collections import Counter, defaultdict
from app.player_data.queue_policy import SUPPORTED_ANALYSIS_QUEUES, SWIFTPLAY_LIMITATION
from copy import deepcopy
from statistics import mean, pstdev
from app.player_data.game_analyser import ANALYSIS_VERSION, HIGH_UNSPENT_GOLD, MAX_STATE_AGE, unspent_gold_context

MIN_RECURRING_GAMES = 3
MIN_PATTERN_GAME_RATE = 0.3
MAX_EXAMPLE_MATCHES = 5
MAX_PATTERN_EXAMPLES = 3
MAX_DEATH_ABILITY_PATTERNS = 20
REPORT_SCHEMA_VERSION = 2
NEUTRAL_DEATH_OBSERVATIONS = {
    "possible_isolation", "possible_overstay", "possible_low_health_exposure",
    "limited_allied_proximity_in_last_snapshot", "low_sampled_health", "large_unspent_gold", "large_unspent_gold_death",
    "enemy_jungler_involved_in_death", "enemy_jungler_involvement",
    "favorable_death_exchange", "unfavorable_death_exchange", "neutral_trade_death",
    "multiple_kills_before_death", "traded_1_for_1", "traded_1_for_2", "traded_1_for_3",
    "enemy_jungler_killed_in_exchange", "enemy_support_killed_in_exchange", "enemy_bottom_or_middle_killed_in_exchange",
    "enemy_objective_after_death", "no_enemy_objective_followup", "allied_objective_followup",
}
UNSUPPORTED_DEATH_METRICS = {"possible_isolation_deaths", "possible_overstay_deaths"}


def champion_key(champion: str) -> str:
    """
    Normalize a champion name for filtering and grouping.
    """
    return "".join(character for character in champion.casefold() if character.isalnum())


def distinct_game_examples(examples: list[dict]) -> list[dict]:
    """
    One example per match, in stable match/timestamp order; never full games.
    """
    selected = []
    seen = set()
    for example in sorted(examples, key=lambda e: (e["match_id"], e.get("timestamp") or -1)):
        if example["match_id"] in seen:
            continue
        seen.add(example["match_id"])
        selected.append(deepcopy(example))
        if len(selected) == MAX_PATTERN_EXAMPLES:
            break
    return selected


def occurrence_examples(entries: list[tuple], games: list[dict]) -> list[dict]:
    """
    Select bounded examples from recorded pattern occurrences.
    """
    players = {game["match_id"]: game["player"] for game in games}
    examples = []
    for match_id, occurrence in entries:
        example = {
            key: occurrence[key]
            for key in ("timestamp", "game_phase", "confidence", "evidence", "valence")
            if key in occurrence
        }
        example.update(
            match_id=match_id,
            champion=occurrence.get("champion", players[match_id]["champion"]),
            role=occurrence.get("role", players[match_id]["role"]),
        )
        examples.append(example)
    return distinct_game_examples(examples)


def reliable_death_abilities(death: dict) -> dict:
    """
    Group reported enemy damage within one death, without spell semantics.
    """
    abilities = {}
    for hit in death.get("ability_hits", []):
        if (
            not hit.get("resolved_participant_id")
            or hit.get("resolved_team_relation") != "enemy"
            or hit.get("attribution_status") not in {None, "resolved", "reported_source_not_verified_effect_owner"}
            or hit.get("basic") is True
            or not hit.get("champion")
            or not hit.get("spell_name")
        ):
            continue
        spell = hit["spell_name"].strip().casefold()
        if not spell:
            continue
        key = (champion_key(hit["champion"]), spell)
        if key not in abilities:
            abilities[key] = {"champion": hit["champion"], "spell_name": spell, "damage": 0, "spell_slots": set()}
        abilities[key]["damage"] += hit.get("damage", 0)
        if isinstance(hit.get("spell_slot"), int):
            abilities[key]["spell_slots"].add(hit["spell_slot"])
    return abilities


def summarize_death_abilities(games: list[dict]) -> dict:
    """
    Aggregate reported enemy ability damage across eligible deaths.
    """
    eligible = [g for g in games if g.get("timeline_observation_available", True) and "deaths" in g]
    grouped = {}
    observed_deaths = 0
    deaths_with_evidence = 0
    seen_deaths = set()
    for game in eligible:
        for death in game["deaths"]:
            if death.get("timestamp") is None:
                continue
            death_id = (game["match_id"], death["timestamp"])
            if death_id in seen_deaths:
                continue
            seen_deaths.add(death_id)
            observed_deaths += 1
            abilities = reliable_death_abilities(death)
            deaths_with_evidence += bool(abilities)
            for key, ability in abilities.items():
                if key not in grouped:
                    grouped[key] = {
                        "champion": ability["champion"],
                        "spell_name": ability["spell_name"],
                        "slots": set(),
                        "deaths": [],
                    }
                grouped[key]["slots"].update(ability["spell_slots"])
                outcome = death.get("death_outcome", {})
                grouped[key]["deaths"].append(
                    {
                        "match_id": game["match_id"],
                        "timestamp": death["timestamp"],
                        "game_phase": death.get("game_state_before", {}).get("phase", {}).get("label", "UNKNOWN"),
                        "damage": ability["damage"],
                        "player_champion": game["player"]["champion"],
                        "role": game["player"]["role"],
                        "outcome_context": {
                            "classification": outcome.get("outcome_classification", "unknown"),
                            "player_kills": outcome.get("player_kills"),
                            "team_kill_differential": outcome.get("team_kill_differential"),
                            "enemy_objective_followup": outcome.get("objective_context", {}).get("enemy_objective_followup"),
                            "interpretation": "observable_outcome_only; decision_quality_not_established",
                        },
                    }
                )
    patterns = []
    for group in grouped.values():
        count_games = len({d["match_id"] for d in group["deaths"]})
        patterns.append(
            {
                "champion": group["champion"],
                "spell_name": group["spell_name"],
                "spell_slots": sorted(group["slots"]),
                "death_occurrences": len(group["deaths"]),
                "games_with_occurrence": count_games,
                "eligible_games": len(eligible),
                "game_rate": round(count_games / len(eligible), 3),
                "example_deaths": distinct_game_examples(group["deaths"]),
                "interpretation": "recorded_damage_involvement_only; does_not_establish_initiation_or_cause",
                "damage_semantics": "grouped_reported_totals_may_include_multiple_hits_or_casts; cast_count_unknown",
            }
        )
    patterns.sort(key=lambda p: (-p["games_with_occurrence"], -p["death_occurrences"], p["champion"], p["spell_name"]))
    return {
        "death_ability_patterns": patterns[:MAX_DEATH_ABILITY_PATTERNS],
        "death_ability_coverage": {
            "eligible_games": len(eligible),
            "games_analyzed": len(games),
            "observed_deaths": observed_deaths,
            "deaths_with_reliable_enemy_ability_evidence": deaths_with_evidence,
            "patterns_omitted": max(0, len(patterns) - MAX_DEATH_ABILITY_PATTERNS),
            "semantics": "unavailable; missing_evidence_does_not_establish_no_engage",
        },
    }


def eligible_unspent_gold_deaths(game: dict) -> list[dict] | None:
    """
    Recheck legacy and current death snapshots against role spending thresholds before summarizing gold signals.
    """
    if "deaths" not in game or not game.get("timeline_observation_available", True):
        return None
    eligible = []
    for death in game["deaths"]:
        state = death.get("state_before_death")
        age = death.get("evidence_quality", {}).get("state_age_ms")
        context = unspent_gold_context(game["player"].get("role"), state)
        if (state and age is not None and 0 <= age <= MAX_STATE_AGE
                and not context["suppress_unspent_gold_coaching"] and (state.get("current_gold") or 0) >= HIGH_UNSPENT_GOLD):
            eligible.append(death)
    return eligible


def summarize_metrics(games: list[dict]) -> dict:
    """
    Aggregate available metrics with explicit sample counts.
    """
    keys = sorted({key for game in games for key in game["aggregate_metrics"]})
    result = {}
    for key in keys:
        values = [None if key in UNSUPPORTED_DEATH_METRICS else game["aggregate_metrics"].get(key) for game in games]
        if key == "large_unspent_gold_deaths":
            eligible = [eligible_unspent_gold_deaths(game) for game in games]
            values = [len(deaths) if deaths is not None else None for deaths in eligible]
        values = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
        result[key] = {
            "mean": round(mean(values), 2) if values else None,
            "samples": len(values),
            "missing": len(games) - len(values),
            "standard_deviation": round(pstdev(values), 2) if values else None,
        }
    total_seconds = sum(game["duration_seconds"] for game in games)
    result["duration_weighted_cs_per_min"] = {
        "value": (
            round(sum(game["player"]["cs"] for game in games) / (total_seconds / 60), 2) if total_seconds > 0 else None
        ),
        "total_seconds": total_seconds,
    }
    return result


def summarize_patterns(games: list[dict]) -> list[dict]:
    """
    Summarize pattern recurrence and supporting examples across games.
    """
    games = [game for game in games if game.get("timeline_observation_available", True)]
    grouped = defaultdict(list)
    for game in games:
        gold_deaths = eligible_unspent_gold_deaths(game)
        gold_timestamps = {death["timestamp"] for death in gold_deaths} if gold_deaths is not None else set()
        for occurrence in game["pattern_occurrences"]:
            if occurrence["type"] in {"large_unspent_gold", "large_unspent_gold_death"}:
                if occurrence.get("timestamp") not in gold_timestamps:
                    continue
            # Older version-4 JSON remains readable, but its causal labels cannot establish weaknesses.
            if occurrence["type"] in NEUTRAL_DEATH_OBSERVATIONS:
                occurrence = {
                    **occurrence, "valence": "observation",
                    "interpretation": "historical_or_recorded_observation_only; isolation_overstay_and_cause_not_established",
                }
            grouped[(occurrence["type"], occurrence["game_phase"])].append((game["match_id"], occurrence))
    results = []
    for (kind, phase), entries in sorted(grouped.items()):
        ids = sorted({match_id for match_id, _ in entries})
        rate = len(ids) / len(games)
        # Average confidence by game, so many events in one game cannot dominate.
        confidences = [mean([o.get("confidence", 1.0) for mid, o in entries if mid == match_id]) for match_id in ids]
        recurring = len(ids) >= MIN_RECURRING_GAMES and rate >= MIN_PATTERN_GAME_RATE
        sample_cap = 0.4 if len(ids) < 3 else (0.6 if len(ids) < 8 else 0.8)
        confidence = round(min(sample_cap, mean(confidences)), 1)
        results.append(
            {
                "type": kind,
                "game_phase": phase,
                "occurrences": len(entries),
                "games_with_pattern": len(ids),
                "eligible_games": len(games),
                "game_rate": round(rate, 3),
                "occurrences_per_game": round(len(entries) / len(games), 2),
                "status": "recurring_observation" if recurring else "limited_observation",
                "confidence": confidence,
                "confidence_basis": "heuristic_not_calibrated; game_support_and_source_confidence",
                "valence": (entries[0][1]["valence"] if len({o["valence"] for _, o in entries}) == 1
                            else "observation"),
                "example_match_ids": ids[:MAX_EXAMPLE_MATCHES],
                "examples": occurrence_examples(entries, games),
                "champions_with_pattern": dict(Counter(g["player"]["champion"] for g in games if g["match_id"] in ids)),
                "interpretation": ("historical_or_recorded_observation_only; isolation_overstay_and_cause_not_established"
                                   if kind in NEUTRAL_DEATH_OBSERVATIONS
                                   else "recurrence_does_not_establish_cause_or_decision_quality"),
            }
        )
    return results


def summarize_cohort(games: list[dict]) -> dict:
    """
    Summarize metrics and patterns within one comparable cohort.
    """
    durations = [g["duration_seconds"] for g in games]
    patterns = summarize_patterns(games)
    chronological = sorted(
        (g for g in games if g.get("game_start_timestamp") is not None),
        key=lambda g: (g["game_start_timestamp"], g["match_id"]),
    )
    direction = []
    if len(chronological) >= 6:
        split = len(chronological) // 2
        for metric in ("overall_cs_per_min", "post_lane_cs_per_min", "matchup_gold_diff_at_10"):
            older = [g["aggregate_metrics"].get(metric) for g in chronological[:split]]
            recent = [g["aggregate_metrics"].get(metric) for g in chronological[split:]]
            older = [v for v in older if v is not None]
            recent = [v for v in recent if v is not None]
            if len(older) >= 3 and len(recent) >= 3:
                delta = mean(recent) - mean(older)
                direction.append(
                    {
                        "metric": metric,
                        "older_mean": round(mean(older), 2),
                        "recent_mean": round(mean(recent), 2),
                        "delta": round(delta, 2),
                        "older_samples": len(older),
                        "recent_samples": len(recent),
                        "direction": "higher" if delta > 0 else ("lower" if delta < 0 else "unchanged"),
                        "interpretation": "descriptive_change_not_proof_of_skill_change",
                    }
                )
    death_context = {}
    for category in ("phase", "killer_role"):
        counts = Counter()
        for game in games:
            counts.update(game.get("death_context_counts", {}).get(category, {}))
        death_context[category] = dict(counts)
    return {
        "games_analyzed": len(games),
        "aggregate_metrics": summarize_metrics(games),
        **summarize_death_abilities(games),
        "death_context_counts": death_context,
        "duration_seconds": {"min": min(durations), "max": max(durations), "mean": round(mean(durations), 2)},
        "patterns": patterns,
        "metric_direction": direction,
        "strength_trends": [
            p for p in patterns if p["status"] == "recurring_observation" and p["valence"] == "strength_candidate"
        ],
        "weakness_trends": [
            p for p in patterns if p["status"] == "recurring_observation" and p["valence"] == "weakness_candidate"
        ],
    }


def analyze_player(game_analyses: list[dict], champion: str | None = None) -> dict:
    """
    Averages have explicit denominators; unlike roles/queues are never pooled.
    """
    games = []
    seen = set()
    duplicates = 0
    player_ids = set()
    versions = set()
    for game in game_analyses:
        if not all(
            key in game
            for key in (
                "analysis_version",
                "match_id",
                "puuid",
                "player",
                "aggregate_metrics",
                "pattern_occurrences",
                "duration_seconds",
            )
        ):
            raise ValueError("Game analysis lacks aggregation metadata; regenerate it with the current analyzer.")
        if champion is not None and champion_key(game["player"]["champion"]) != champion_key(champion):
            continue
        player_ids.add(game["puuid"])
        versions.add(game["analysis_version"])
        if game["match_id"] in seen:
            duplicates += 1
            continue
        seen.add(game["match_id"])
        games.append(game)
    if len(player_ids) > 1:
        raise ValueError("Cannot combine different players.")
    if len(versions) > 1:
        raise ValueError("Regenerate analyses to use one analysis version before aggregation.")
    if versions and versions != {ANALYSIS_VERSION}:
        raise ValueError("Regenerate game analyses with the current analysis version before aggregation.")
    groups = defaultdict(list)
    for game in games:
        key = (game["player"]["role"], game["player"]["champion"], game["queue_id"])
        groups[key].append(game)
    cohorts = [
        {"role": role, "champion": champ, "queue_id": queue, "queue_name": SUPPORTED_ANALYSIS_QUEUES.get(queue),
         **summarize_cohort(group)}
        for (role, champ, queue), group in sorted(groups.items(), key=lambda entry: str(entry[0]))
    ]
    role_groups = defaultdict(list)
    for game in games:
        role_groups[(game["player"]["role"], game["queue_id"])].append(game)
    role_cohorts = [
        {"role": role, "queue_id": queue, "queue_name": SUPPORTED_ANALYSIS_QUEUES.get(queue),
         **summarize_cohort(group)}
        for (role, queue), group in sorted(role_groups.items(), key=lambda entry: str(entry[0]))
    ]
    timestamps = [g["game_start_timestamp"] for g in games if g.get("game_start_timestamp") is not None]
    patterns = [
        {**p, "role": c["role"], "queue_id": c["queue_id"]}
        for c in role_cohorts
        for p in c["patterns"]
        if p["status"] == "recurring_observation"
    ]
    homogeneous = len({(g["player"]["role"], g["queue_id"]) for g in games}) == 1
    report = {
        "analysis_version": ANALYSIS_VERSION,
        "death_evidence_version": 3,
        "schema_version": REPORT_SCHEMA_VERSION,
        "puuid": games[0]["puuid"] if games else None,
        "champion_filter": champion,
        "games_analyzed": len(games),
        "duplicate_games_ignored": duplicates,
        "date_range": {
            "start_ms": min(timestamps) if timestamps else None,
            "end_ms": max(timestamps) if timestamps else None,
            "games_with_dates": len(timestamps),
        },
        "champions_played": dict(Counter(g["player"]["champion"] for g in games)),
        "roles_played": dict(Counter(g["player"]["role"] for g in games)),
        "patches": dict(Counter(g.get("game_version", "unknown") for g in games)),
        "wins": sum(g["player"]["win"] is True for g in games),
        "aggregate_metrics": summarize_metrics(games) if games and homogeneous else {},
        "aggregation_scope": "same_role_and_queue" if homogeneous else "use_separate_cohorts",
        "cohorts": cohorts,
        "role_cohorts": role_cohorts,
        "strength_trends": [p for p in patterns if p["valence"] == "strength_candidate"],
        "weakness_trends": [p for p in patterns if p["valence"] == "weakness_candidate"],
        "high_confidence_patterns": [p for p in patterns if p["confidence"] >= 0.8],
        "low_confidence_patterns": [p for p in patterns if p["confidence"] < 0.8],
        "limitations": [
            "Sample is retrieved games, not an unbiased measure of player skill.",
            "Missing metrics are excluded with denominators; unknown engage evidence is not zero.",
            "Fights are kill-event clusters; recorded participation can be incomplete.",
            "Win/loss is context only. Trends describe observations, not causal coaching.",
            "Patterns are separated by champion, role, queue and phase; phase labels are approximate.",
            "Ability counts are recorded damage involvement, not initiation, CC, engage importance or mistake causality.",
            "Top-level and cohort summaries are overlapping views; do not sum their counts together.",
            "Missing or excluded ability evidence does not mean no ability or engage occurred.",
            "Legacy isolation/overstay labels are unvalidated observations, never confirmed recurring mistakes.",
            "Historical proximity and health do not establish death-time isolation, fight-entry health or safe recalls.",
            "Grouped damage may include multiple hits/casts; ally protection and spell availability remain unknown.",
            "Death-outcome patterns are recorded exchanges, not good/bad decisions or proof of objective prevention.",
            "Unspent-gold signals are suppressed at role spending thresholds; inventory completion is not established.",
        ],
    }
    if any(game["queue_id"] == 480 for game in games):
        report["limitations"].append(SWIFTPLAY_LIMITATION)
    # Homogeneous reports expose the useful summary directly; mixed reports retain cohort boundaries.
    report["death_ability_patterns"] = role_cohorts[0]["death_ability_patterns"] if homogeneous else []
    report["death_ability_coverage"] = (
        role_cohorts[0]["death_ability_coverage"] if homogeneous else {"status": "use_separate_cohorts"}
    )
    if not games:
        report.update(summarize_death_abilities([]))
    if len(cohorts) == 1:
        for key in ("death_context_counts", "patterns", "metric_direction"):
            report[key] = cohorts[0][key]
    return report
