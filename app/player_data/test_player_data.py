"""Offline regression tests. Run: python -m unittest -v test_player_data"""

import json
from pathlib import Path
import sys
import unittest
import io
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.player_data.match_parser import parse_match
from app.player_data.timeline_parser import parse_timeline, parse_damage_sources
from app.player_data.game_analyser import (
    analyze_game,
    analyze_death,
    group_fights,
    get_event_team,
    build_coaching_signals,
    player_died_recently,
    outcome_window_metadata,
    print_death_summary,
)


def sample_match(duration=1920):
    """
    Build a synthetic match summary for tests.
    """
    roles = ["BOTTOM", "UTILITY", "JUNGLE", "MIDDLE", "TOP"] * 2
    champions = [
        "Player",
        "AllySupport",
        "AllyJungle",
        "AllyMid",
        "AllyTop",
        "Kaisa",
        "Nautilus",
        "Warwick",
        "EnemyMid",
        "EnemyTop",
    ]
    participants = [
        dict(
            participantId=i,
            puuid=str(i),
            teamId=100 if i <= 5 else 200,
            teamPosition=roles[i - 1],
            championName=champions[i - 1],
            riotIdGameName="Test",
            riotIdTagline="TEST",
            win=True,
            kills=2,
            deaths=1,
            assists=1,
            totalMinionsKilled=240,
            neutralMinionsKilled=16,
            goldEarned=12000,
            champLevel=16,
        )
        for i in range(1, 11)
    ]
    return {
        "metadata": {"matchId": "TEST"},
        "info": {
            "participants": participants,
            "gameDuration": duration,
            "gameVersion": "test",
            "queueId": 420,
            "mapId": 11,
        },
    }


def hit(pid, spell, damage=145):
    """
    Build a reported damage record for a test event.
    """
    return {
        "participantId": pid,
        "spellName": spell,
        "spellSlot": 0,
        "name": {6: "Kaisa", 7: "Nautilus", 8: "Warwick"}.get(pid, "Turret"),
        "basic": False,
        "magicDamage": damage,
        "physicalDamage": 0,
        "trueDamage": 0,
    }


def kill(timestamp=939000, killer=6, victim=1, assists=None, sources=None, x=5000, y=5000):
    """
    Build a champion kill event for tests.
    """
    return {
        "type": "CHAMPION_KILL",
        "timestamp": timestamp,
        "killerId": killer,
        "victimId": victim,
        "assistingParticipantIds": [7] if assists is None else assists,
        "position": {"x": x, "y": y},
        "victimDamageReceived": sources or [],
    }


def fixture(events=None, minutes=32):
    """
    Build a synthetic timeline and parsed match for analysis tests.
    """
    events = events or []
    frames = []
    for minute in range(minutes + 1):
        participants = {}
        for pid in range(1, 11):
            position = {"x": 5000, "y": 5000} if pid in {1, 2, 6, 7} else {"x": 13000, "y": 13000}
            participants[str(pid)] = {
                "participantId": pid,
                "totalGold": 500 + minute * 300,
                "currentGold": 500,
                "xp": minute * 200,
                "level": 1 + minute // 2,
                "minionsKilled": minute * 6,
                "jungleMinionsKilled": 0,
                "championStats": {"health": 700, "healthMax": 1000},
                "position": position,
            }
        frames.append(
            {
                "timestamp": minute * 60000,
                "participantFrames": participants,
                "events": [e for e in events if (minute - 1) * 60000 < e["timestamp"] <= minute * 60000],
            }
        )
    raw = {"info": {"frames": frames}}
    match = parse_match(sample_match(minutes * 60), "1")
    return raw, match


class EvidenceTests(unittest.TestCase):
    def test_dead_snapshot_from_previous_death_is_not_encounter_context(self):
        """
        Verify dead snapshot from previous death is not encounter context.
        """
        raw, match = fixture([kill(878000), kill(939000)])
        raw["info"]["frames"][15]["participantFrames"]["1"]["championStats"]["health"] = 0
        death = analyze_game(parse_timeline(raw, 1, 6), match)["deaths"][1]
        self.assertEqual(death["encounter_context_status"], "sampled_dead_following_earlier_death")
        self.assertEqual(death["historical_snapshot"]["health"], 0)
        self.assertIsNone(death["state_before_death"])
        self.assertIsNone(death["health_ratio_before"])
        self.assertFalse(death["two_samples_without_allies"])
        self.assertEqual(death["cause_candidates"], [])

    def test_snapshot_before_previous_death_is_not_reused(self):
        """
        Verify snapshot before previous death is not reused.
        """
        raw, match = fixture([kill(910000), kill(939000)])
        death = analyze_game(parse_timeline(raw, 1, 6), match)["deaths"][1]
        self.assertEqual(death["encounter_context_status"], "snapshot_not_valid_for_current_life")
        self.assertIsNone(death["state_before_death"])

    def test_identity_conflict_keeps_reports_but_not_resolved_attribution(self):
        """
        Verify identity conflict keeps reports but not resolved attribution.
        """
        source = hit(8, "burning")
        source["name"] = "Kaisa"
        death = self.analysis([kill(assists=[], sources=[source])])["deaths"][0]
        damage = death["damage_sources"][0]
        self.assertEqual(damage["source_name"], "Kaisa")
        self.assertEqual(damage["participant_champion"], "Warwick")
        self.assertEqual(damage["attribution_status"], "identity_conflict")
        self.assertEqual(damage["resolved_team_relation"], "unknown")
        self.assertIsNone(damage["resolved_participant_id"])
        self.assertFalse(death["jungler_involved"])

    def test_fight_includes_damage_only_contributor(self):
        """
        Verify fight includes damage only contributor.
        """
        result = self.analysis(
            [
                kill(900000, assists=[], sources=[hit(7, "nautilusanchordrag")]),
                kill(905000, victim=2, assists=[], sources=[hit(8, "warwickq")]),
            ]
        )
        fight = result["fights"][0]
        self.assertIn(7, fight["participants"])
        self.assertIn(8, fight["participants"])
        evidence = {p["participant_id"]: p["evidence_types"] for p in fight["participant_evidence"]}
        self.assertEqual(evidence[7], ["reported_damage"])
        self.assertEqual(evidence[8], ["reported_damage"])

    def test_delayed_milestone_snapshots(self):
        """
        Verify delayed milestone snapshots.
        """
        raw, match = fixture()
        for frame in raw["info"]["frames"][1:]:
            frame["timestamp"] += 337
        result = analyze_game(parse_timeline(raw, 1, 6), match)["cs_analysis"]
        self.assertEqual(result["matchup_cs_sample_timestamp"], 600337)
        self.assertEqual(result["lane_boundary"]["sample_timestamp"], 840337)
        self.assertEqual(result["lane_cs"], 84)
        self.assertEqual(result["lane_boundary"]["sample_offset_ms"], 337)

    def test_missing_milestone_is_not_previous_minute(self):
        """
        Verify missing milestone is not previous minute.
        """
        raw, match = fixture()
        raw["info"]["frames"] = [f for f in raw["info"]["frames"] if f["timestamp"] not in {600000, 840000}]
        result = analyze_game(parse_timeline(raw, 1, 6), match)["cs_analysis"]
        self.assertIsNone(result["matchup_cs_diff_at_10"])
        self.assertIsNone(result["lane_cs"])

    def test_gold_window_coverage(self):
        """
        Verify gold window coverage.
        """
        result = outcome_window_metadata(1094839, 1916868, {"timestamp": 1080403}, {"timestamp": 1140411})
        self.assertEqual(result["event_window"]["end_inclusive"], 1184839)
        self.assertEqual(result["gold_window"]["post_death_covered_ms"], 45572)
        self.assertEqual(result["gold_window"]["uncovered_event_tail_ms"], 44428)
        self.assertEqual(result["gold_window"]["pre_death_included_ms"], 14436)
        missing = outcome_window_metadata(1000, 2000, None, None)
        self.assertFalse(missing["gold_window"]["available"])
        self.assertEqual(missing["event_window"]["observed_duration_ms"], 1000)

    def test_allied_and_unknown_damage_attribution(self):
        """
        Verify allied and unknown damage attribution.
        """
        death = self.analysis([kill(sources=[hit(3, "burning"), hit(0, "effect"), hit(6, "kaisaq")])])["deaths"][0]
        sources = {s["participant_id"]: s for s in death["damage_sources"]}
        self.assertEqual(sources[3]["source_team_relation"], "allied")
        self.assertEqual(sources[0]["source_team_relation"], "unknown")
        self.assertEqual(sources[6]["source_team_relation"], "enemy")
        self.assertEqual(sources[3]["damage"], 145)
        self.assertNotIn(3, [a["participant_id"] for a in death["attackers"]])
        self.assertEqual(sources[3]["interpretation_note"], "does_not_establish_allied_attack")

    def test_console_explains_missing_candidates_and_samples(self):
        """
        Verify console explains missing candidates and samples.
        """
        death = self.analysis([kill()])["deaths"][0]
        output = io.StringIO()
        with redirect_stdout(output):
            print_death_summary(death)
        for phrase in (
            "Sampled nearby enemies",
            "age (ms)",
            "approximate spent gold",
            "not_a_no_mistake_verdict",
            "Separate sampled team gold change",
        ):
            self.assertIn(phrase, output.getvalue())

    def analysis(self, events=None):
        """
        Analyze the supplied synthetic events for a test.
        """
        raw, match = fixture(events)
        return analyze_game(parse_timeline(raw, 1, 6), match)

    def test_post_death_2958_explains_30_to_31(self):
        """
        Verify post death 2958 explains 30 to 31.
        """
        raw, match = fixture([kill(1798000)])
        for frame in raw["info"]["frames"][30:32]:
            frame["participantFrames"]["1"]["minionsKilled"] = 174
        analysis = analyze_game(parse_timeline(raw, 1, 6), match)
        window = next(w for w in analysis["farm_windows"] if w["start_time"] == "30:00")
        self.assertEqual(window["classification"]["reason"], "post_death_downtime")

    def test_normal_two_vs_two_not_isolation(self):
        """
        Verify normal two vs two not isolation.
        """
        death = self.analysis([kill(sources=[hit(6, "kaisaq"), hit(7, "nautilusanchordrag")])])["deaths"][0]
        self.assertEqual(death["attacker_count"], 2)
        self.assertFalse(any("isolat" in c["type"] for c in death["cause_candidates"]))

    def test_kaisa_damage_not_engage(self):
        """
        Verify kaisa damage not engage.
        """
        death = self.analysis([kill(assists=[], sources=[hit(6, "kaisaq"), hit(6, "kaisapassive")])])["deaths"][0]
        self.assertEqual(len(death["ability_hits"]), 2)
        self.assertEqual(death["important_spell_hits"], [])
        self.assertFalse(any("engage" in c["type"] for c in death["cause_candidates"]))

    def test_hook_remains_available(self):
        """
        Verify hook remains available.
        """
        death = self.analysis([kill(sources=[hit(7, "nautilusanchordrag")])])["deaths"][0]
        self.assertEqual(death["ability_hits"][0]["spell_name"], "nautilusanchordrag")
        self.assertEqual(death["ability_hits"][0]["damage"], 145)
        self.assertEqual(death["killer_champion"], "Kaisa")

    def test_jungler_fact_survives_position_disagreement(self):
        """
        Verify jungler fact survives position disagreement.
        """
        death = self.analysis([kill(878000, assists=[7, 8], sources=[hit(8, "warwickr")])])["deaths"][0]
        self.assertTrue(death["jungler_involved"])
        self.assertIn(8, [a["participant_id"] for a in death["attackers"]])
        self.assertIsNone(death["nearby_enemies"])
        historical = death["proximity_snapshot"]["historical_observed_enemies"]
        self.assertNotIn(8, [a["participant_id"] for a in historical])
        self.assertEqual(death["evidence_quality"]["position_age_ms"], 38000)

    def test_positive_team_gold_not_good_death(self):
        """
        Verify positive team gold not good death.
        """
        raw, match = fixture([kill()])
        for frame in raw["info"]["frames"][16:]:
            frame["participantFrames"]["3"]["totalGold"] += 2000
        death = analyze_game(parse_timeline(raw, 1, 6), match)["deaths"][0]
        self.assertGreater(death["team_outcome_after"]["team_gold_diff_change"], 0)
        self.assertEqual(death["personal_outcome"]["decision_quality"], "not_determined")
        self.assertEqual(death["team_outcome_after"]["causality"], "not_established")

    def test_absolute_farm_and_matchup_metrics(self):
        """
        Verify absolute farm and matchup metrics.
        """
        metrics = self.analysis()["cs_analysis"]
        self.assertEqual(metrics["overall_cs_per_min"], 8)
        self.assertEqual(metrics["overall_cs"], 256)
        self.assertIsNotNone(metrics["lane_cs_per_wave"])
        self.assertIsNotNone(metrics["post_lane_cs_per_min"])
        self.assertEqual(metrics["matchup_cs_diff_at_10"], 0)

    def test_structure_and_objective_followups(self):
        """
        Verify structure and objective followups.
        """
        events = [
            kill(),
            {
                "type": "BUILDING_KILL",
                "timestamp": 960000,
                "killerId": 0,
                "teamId": 100,
                "buildingType": "TOWER_BUILDING",
                "towerType": "OUTER_TURRET",
                "laneType": "BOT_LANE",
            },
            {
                "type": "ELITE_MONSTER_KILL",
                "timestamp": 965000,
                "killerTeamId": 200,
                "killerId": 8,
                "monsterType": "BARON_NASHOR",
            },
        ]
        death = self.analysis(events)["deaths"][0]
        self.assertEqual(death["team_outcome_after"]["structures"][0]["team_id"], 200)
        self.assertEqual(death["team_outcome_after"]["objectives"][0]["timestamp"], 965000)

    def test_interleaved_fights_and_thirty_second_gap(self):
        """
        Verify interleaved fights and thirty second gap.
        """
        raw, _ = fixture([kill(900000), kill(905000, x=13000, y=13000), kill(927000)])
        fights = group_fights(parse_timeline(raw, 1, 6))
        self.assertEqual(len(fights), 1)
        self.assertEqual([e["timestamp"] for e in fights[0]], [900000, 927000])

    def test_missing_opponent(self):
        """
        Verify missing opponent.
        """
        raw, match = fixture()
        match["opponent"] = None
        result = analyze_game(parse_timeline(raw, 1, None), match)
        self.assertIsNone(result["cs_analysis"]["matchup_cs_diff_at_10"])

    def test_empty_timeline_and_short_game(self):
        """
        Verify empty timeline and short game.
        """
        raw, match = fixture(minutes=3)
        result = analyze_game(parse_timeline(raw, 1, 6), match)
        self.assertIsNone(result["cs_analysis"]["matchup_cs_diff_at_10"])
        raw["info"]["frames"] = []
        result = analyze_game(parse_timeline(raw, 1, None), match)
        self.assertEqual(result["deaths"], [])

    def test_non_champion_damage_and_missing_spell_retained(self):
        """
        Verify non champion damage and missing spell retained.
        """
        sources = parse_damage_sources({"victimDamageReceived": [hit(0, ""), hit(7, "")]})
        self.assertEqual(len(sources), 2)
        self.assertEqual(sum(s["damage"] for s in sources), 290)

    def test_compact_default_and_debug_opt_in(self):
        """
        Verify compact default and debug opt in.
        """
        raw, match = fixture([kill()])
        parsed = parse_timeline(raw, 1, 6)
        compact = analyze_game(parsed, match)
        debug = analyze_game(parsed, match, include_windows=True)
        self.assertNotIn("windows", compact)
        self.assertEqual(len(debug["windows"]), 32)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(raw)) // 2)

    def test_no_role_does_not_match_another_unknown_role(self):
        """
        Verify no role does not match another unknown role.
        """
        raw = sample_match()
        for participant in raw["info"]["participants"]:
            participant["teamPosition"] = ""
        self.assertIsNone(parse_match(raw, "1")["opponent"])

    def test_enemy_conversion_does_not_count_for_player_team(self):
        """
        Verify enemy conversion does not count for player team.
        """
        fight = {
            "player_involved": True,
            "kill_differential": 3,
            "player_team_id": 100,
            "start_timestamp": 100,
            "conversion_observed_seconds": 90,
            "objectives_after": [{"team_id": 200}],
            "structures_after": [],
        }
        signals = build_coaching_signals({}, [], [], [fight])
        self.assertEqual(signals[0]["type"], "fight_conversion_review_candidate")
        fight["objectives_after"][0]["team_id"] = 100
        self.assertEqual(build_coaching_signals({}, [], [], [fight]), [])
        fight["objectives_after"] = []
        fight["conversion_observed_seconds"] = 30
        self.assertEqual(build_coaching_signals({}, [], [], [fight]), [])

    def test_stale_low_health_is_not_cause(self):
        """
        Verify stale low health is not cause.
        """
        raw, match = fixture([kill()])
        raw["info"]["frames"][15]["participantFrames"]["1"]["championStats"]["health"] = 100
        death = analyze_game(parse_timeline(raw, 1, 6), match)["deaths"][0]
        self.assertEqual(death["health_ratio_before"], 0.1)
        self.assertFalse(any("health" in c["type"] for c in death["cause_candidates"]))

    def test_observed_farming_ends_recent_death_classification(self):
        """
        Verify observed farming ends recent death classification.
        """
        raw, _ = fixture([kill(1739000)])
        timeline = parse_timeline(raw, 1, 6)
        self.assertFalse(player_died_recently({"start_timestamp": 1800000}, timeline))

    def test_teammate_lane_cs_absorption_is_inference(self):
        """
        Verify teammate lane cs absorption is inference.
        """
        raw, match = fixture()
        raw["info"]["frames"][11]["participantFrames"]["1"]["minionsKilled"] = 61
        analysis = analyze_game(parse_timeline(raw, 1, 6), match)
        window = next(w for w in analysis["farm_windows"] if w["start_time"] == "10:00")
        self.assertEqual(window["classification"]["reason"], "possible_teammate_wave_absorption")
        self.assertEqual(window["classification"]["confidence"], 0.5)

    def test_exact_death_frame_is_not_predeath_health(self):
        """
        Verify exact death frame is not predeath health.
        """
        raw, match = fixture([kill(900000)])
        raw["info"]["frames"][15]["participantFrames"]["1"]["championStats"]["health"] = 0
        death = analyze_game(parse_timeline(raw, 1, 6), match)["deaths"][0]
        self.assertEqual(death["state_before_death"]["sample_timestamp"], 840000)

    def test_unknown_health_is_not_zero_health(self):
        """
        Verify unknown health is not zero health.
        """
        raw, match = fixture([kill()])
        raw["info"]["frames"][15]["participantFrames"]["1"]["championStats"] = {}
        death = analyze_game(parse_timeline(raw, 1, 6), match)["deaths"][0]
        self.assertIsNone(death["health_ratio_before"])

    def test_wards_and_new_objective_names_are_preserved(self):
        """
        Verify wards and new objective names are preserved.
        """
        events = [
            {"type": "WARD_PLACED", "timestamp": 930000, "creatorId": 2, "wardType": "YELLOW_TRINKET"},
            kill(),
            {
                "type": "ELITE_MONSTER_KILL",
                "timestamp": 960000,
                "killerId": 1,
                "killerTeamId": 100,
                "monsterType": "FUTURE_RIOT_OBJECTIVE",
            },
        ]
        analysis = self.analysis(events)
        self.assertIsNone(analysis["deaths"][0]["recent_ward_events"][0]["position"])
        self.assertEqual(analysis["resource_events"][0]["monster_type"], "FUTURE_RIOT_OBJECTIVE")
        self.assertTrue(analysis["resource_events"][0]["player_recorded_participation"])


if __name__ == "__main__":
    unittest.main()
