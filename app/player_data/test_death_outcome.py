"""Offline outcome-first death review and role spending-threshold regressions."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.player_data.game_analyser import analyze_game, has_effectively_completed_build, unspent_gold_context
from app.player_data.player_analyzer import analyze_player
from app.player_data.timeline_parser import parse_timeline
from test_player_data import fixture, kill, hit


DEATH_TIME = 902000


def objective(timestamp, team=200, monster="DRAGON", subtype="AIR_DRAGON"):
    """
    Build an objective capture event with an explicitly recorded gaining team.
    """
    return {
        "type": "ELITE_MONSTER_KILL",
        "timestamp": timestamp,
        "killerId": 8 if team == 200 else 3,
        "killerTeamId": team,
        "monsterType": monster,
        "monsterSubType": subtype,
    }


def tower(timestamp, team=100, x=5100, y=5000, tower_type="OUTER_TURRET"):
    """
    Build a destruction record whose team identifies the structure owner.
    """
    return {
        "type": "BUILDING_KILL",
        "timestamp": timestamp,
        "teamId": team,
        "killerId": 6,
        "buildingType": "TOWER_BUILDING",
        "towerType": tower_type,
        "laneType": "BOT_LANE",
        "position": {"x": x, "y": y},
    }


def outcome_game(kills=0, extras=None, role="BOTTOM", spent=10000, unspent=500, index=0):
    """
    Analyze a controlled exchange and one death with explicit snapshot spending.
    """
    events = [
        kill(DEATH_TIME - 12000 + i * 4000, killer=1, victim=victim, assists=[])
        for i, victim in enumerate((8, 7, 6)[:kills])
    ]
    events.append(kill(DEATH_TIME, killer=6, assists=[7, 8], sources=[hit(6, "twitchfullautomatic", 890)]))
    events.extend(extras or [])
    raw, match = fixture(events)
    state = raw["info"]["frames"][15]["participantFrames"]["1"]
    state["totalGold"] = spent + unspent
    state["currentGold"] = unspent
    match["player"]["role"] = role
    match["player"]["champion"] = "Xayah"
    match["match_id"] = f"OUTCOME_{index}"
    return analyze_game(parse_timeline(raw, 1, 6), match)


class DeathOutcomeTests(unittest.TestCase):
    def test_zero_one_two_three_kill_trades(self):
        """
        Classify recorded 0-for-1, 1-for-1, 2-for-1, and 3-for-1 exchanges independently of blame.
        """
        for count, expected in ((0, "unfavorable"), (1, "even"), (2, "favorable"), (3, "favorable")):
            with self.subTest(kills=count):
                death = outcome_game(count)["deaths"][0]
                outcome = death["death_outcome"]
                self.assertEqual(outcome["outcome_classification"], expected)
                self.assertEqual(outcome["player_kills"], count)
                self.assertEqual(outcome["team_kill_differential"], count - 1)
                self.assertEqual(outcome["personal_kill_trade"]["differential"], count - 1)
                self.assertEqual(death["personal_outcome"]["decision_quality"], "not_determined")
                self.assertEqual(outcome["window_before_ms"], 15000)
                self.assertEqual(outcome["window_after_ms"], 30000)
                self.assertEqual(outcome["objective_context"]["window_after_ms"], 45000)

    def test_two_personal_kills_plus_ally_kill(self):
        """
        Preserve personal and team value separately without generating a weakness.
        """
        game = outcome_game(2, [kill(DEATH_TIME + 2000, killer=2, victim=9, assists=[1])])
        outcome = game["deaths"][0]["death_outcome"]
        self.assertEqual(outcome["outcome_classification"], "favorable")
        self.assertEqual((outcome["player_kills"], outcome["player_assists"], outcome["allied_kills"]), (2, 1, 3))
        self.assertEqual(outcome["player_kills_by_timing"], {"before": 2, "at": 0, "after": 0})
        self.assertIn("multiple_kills_before_death", outcome["signals"])
        self.assertEqual(game["weakness_signals"], [])
        aggregated = analyze_player([game])
        example = aggregated["death_ability_patterns"][0]["example_deaths"][0]
        self.assertEqual(example["outcome_context"]["classification"], "favorable")
        self.assertEqual(example["outcome_context"]["team_kill_differential"], 2)

    def test_posthumous_kill_is_labeled_after_death(self):
        """
        Distinguish a posthumous trade from a kill secured before death.
        """
        death = outcome_game(0, [kill(DEATH_TIME + 3000, killer=1, victim=8, assists=[])])["deaths"][0]
        self.assertEqual(death["death_outcome"]["outcome_classification"], "even")
        self.assertEqual(death["death_outcome"]["player_kills_by_timing"]["after"], 1)
        self.assertNotIn("multiple_kills_before_death", death["death_outcome"]["signals"])

    def test_enemy_jungler_support_and_shutdown_evidence(self):
        """
        Retain which enemies died and any reported shutdown amount.
        """
        event = kill(DEATH_TIME - 8000, killer=1, victim=8, assists=[])
        event["shutdownBounty"] = 600
        death = outcome_game(0, [event, kill(DEATH_TIME - 4000, killer=1, victim=7, assists=[])])["deaths"][0]
        outcome = death["death_outcome"]
        self.assertIn("enemy_jungler_killed_in_exchange", outcome["signals"])
        self.assertIn("enemy_support_killed_in_exchange", outcome["signals"])
        self.assertEqual(outcome["enemy_champions_killed"][0]["shutdown_bounty"], 600)
        self.assertIn("not_exact_fight_numbers", outcome["participant_count_semantics"])

    def test_distinct_nearby_deaths_keep_different_classifications(self):
        """
        Keep favorable and unfavorable deaths in the same three-minute period independent.
        """
        game = outcome_game(2, [kill(DEATH_TIME + 90000)])
        self.assertEqual(
            [death["death_outcome"]["outcome_classification"] for death in game["deaths"]], ["favorable", "unfavorable"]
        )
        self.assertEqual(
            [death["death_outcome"]["timestamp"] for death in game["deaths"]], [DEATH_TIME, DEATH_TIME + 90000]
        )

    def test_overlapping_deaths_mark_uncertainty(self):
        """
        Avoid confidently assigning shared exchange outcomes across closely overlapping deaths.
        """
        game = outcome_game(0, [kill(DEATH_TIME + 10000)])
        self.assertEqual(len(game["deaths"]), 2)
        self.assertEqual(
            [death["death_outcome"]["outcome_classification"] for death in game["deaths"]], ["unclear", "unclear"]
        )

    def test_remote_kills_do_not_improve_local_exchange(self):
        """
        Keep unrelated kills elsewhere on the map out of the player's kill trade.
        """
        game = outcome_game(0, [kill(DEATH_TIME - 4000, killer=4, victim=9, assists=[], x=14000, y=14000)])
        outcome = game["deaths"][0]["death_outcome"]
        self.assertEqual(outcome["allied_kills"], 0)
        self.assertEqual(outcome["outcome_classification"], "unfavorable")
        self.assertEqual(len(outcome["other_kills_in_time_window"]), 1)

    def test_cluster_mapping_and_extended_cluster_uncertainty(self):
        """
        Match stable fight identifiers and flag clusters extending beyond the bounded death window.
        """
        game = outcome_game(2)
        self.assertEqual(game["deaths"][0]["fight_context"]["fight_id"], game["fights"][0]["fight_id"])
        game = outcome_game(1, [kill(DEATH_TIME - 35000, killer=2, victim=9, assists=[])])
        self.assertEqual(game["deaths"][0]["death_outcome"]["outcome_classification"], "unclear")
        self.assertEqual(game["deaths"][0]["fight_context"]["allied_kills"], 2)

    def test_enemy_dragon_followup_and_no_capture_semantics(self):
        """
        Describe captures and observed non-captures without claiming prevention.
        """
        outcome = outcome_game(0, [objective(DEATH_TIME + 20000)])["deaths"][0]["death_outcome"]
        self.assertEqual(outcome["outcome_classification"], "unfavorable")
        context = outcome["objective_context"]
        self.assertTrue(context["enemy_objective_followup"])
        self.assertEqual(context["objectives_after"][0]["monster_type"], "DRAGON")
        self.assertIn("enemy_objective_after_death", outcome["signals"])
        empty = outcome_game(2)["deaths"][0]["death_outcome"]
        self.assertFalse(empty["objective_context"]["enemy_objective_followup"])
        self.assertIn("no_enemy_objective_followup", empty["signals"])
        self.assertIn("absence_does_not_establish_prevention", empty["objective_context"]["interpretation"])

    def test_objective_boundary_and_conflicting_value(self):
        """
        Respect the short objective window and mark conflicting trade value as unclear.
        """
        for delay, expected in ((45000, "unclear"), (45001, "favorable")):
            with self.subTest(delay=delay):
                outcome = outcome_game(2, [objective(DEATH_TIME + delay)])["deaths"][0]["death_outcome"]
                self.assertEqual(outcome["outcome_classification"], expected)

    def test_missing_frames_and_truncated_followup_are_not_absence(self):
        """
        Mark incomplete observation coverage unknown rather than assert no objective was captured.
        """
        for mode in ("gap", "truncated"):
            raw, match = fixture([kill(DEATH_TIME)])
            if mode == "gap":
                del raw["info"]["frames"][14]
            else:
                raw["info"]["frames"] = raw["info"]["frames"][:17]
                raw["info"]["frames"][-1]["timestamp"] = DEATH_TIME + 10000
            outcome = analyze_game(parse_timeline(raw, 1, 6), match)["deaths"][0]["death_outcome"]
            with self.subTest(mode=mode):
                self.assertEqual(outcome["outcome_classification"], "unclear")
                if mode == "truncated":
                    self.assertIsNone(outcome["objective_context"]["enemy_objective_followup"])
                    self.assertNotIn("no_enemy_objective_followup", outcome["signals"])

    def test_unknown_killer_attribution_is_unclear(self):
        """
        Avoid inventing a team kill credit for turret or unresolved killers.
        """
        raw, match = fixture([kill(DEATH_TIME, killer=0, assists=[])])
        outcome = analyze_game(parse_timeline(raw, 1, 6), match)["deaths"][0]["death_outcome"]
        self.assertEqual(outcome["outcome_classification"], "unclear")
        self.assertIn("unclear_kill_attribution", outcome["uncertainties"])

    def test_allied_turret_location_is_descriptive(self):
        """
        Measure a recorded standing allied turret without inferring wave collection or overextension.
        """
        game = outcome_game(1, [tower(DEATH_TIME + 50000)])
        death = game["deaths"][0]
        self.assertEqual(death["death_outcome"]["outcome_classification"], "even")
        context = death["death_location_context"]
        self.assertTrue(context["near_allied_turret"])
        self.assertEqual(context["turret_distance"], 100)
        self.assertIn("intent_and_turret_protection_unknown", context["interpretation"])
        self.assertFalse(any("overextend" in c["type"] for c in death["cause_candidates"]))

    def test_destroyed_enemy_and_respawning_turrets_are_not_allied_cover(self):
        """
        Leave turret context unknown when a standing allied outer or inner turret is not established.
        """
        for event in (
            tower(DEATH_TIME - 1000),
            tower(DEATH_TIME + 1000, team=200),
            tower(DEATH_TIME + 1000, tower_type="NEXUS_TURRET"),
        ):
            with self.subTest(event=event):
                self.assertIsNone(outcome_game(0, [event])["deaths"][0]["death_location_context"]["near_allied_turret"])

    def test_soul_point_is_conditional_not_available_or_saved(self):
        """
        Expose three recorded elemental dragons without claiming availability or counterfactual prevention.
        """
        prior = [objective(timestamp) for timestamp in (100000, 400000, 700000)]
        context = outcome_game(2, prior)["deaths"][0]["death_outcome"]["objective_context"]
        self.assertTrue(context["dragon_context"]["enemy_next_elemental_dragon_would_grant_soul"])
        self.assertIsNone(context["dragon_context"]["dragon_available"])
        self.assertFalse(context["dragon_context"]["enemy_dragon_captured_after_death"])
        context = outcome_game(2, prior + [objective(800000, subtype="ELDER_DRAGON")])["deaths"][0]["death_outcome"][
            "objective_context"
        ]
        self.assertEqual(context["dragon_context"]["enemy_elemental_dragons_recorded"], 3)
        self.assertFalse(context["dragon_context"]["enemy_next_elemental_dragon_would_grant_soul"])

    def test_ability_damage_remains_evidence_without_mechanical_advice(self):
        """
        Retain large recorded damage while reporting the favorable trade before any interpretation.
        """
        death = outcome_game(2)["deaths"][0]
        self.assertEqual(death["ability_hits"][0]["damage"], 890)
        self.assertEqual(death["death_outcome"]["outcome_classification"], "favorable")
        self.assertIn("spell_availability", death["unknowns"])
        self.assertNotIn("recommendations", death)
        self.assertNotIn("flank", " ".join(c["type"] for c in death["cause_candidates"]))

    def test_favorable_and_unfavorable_recurrence_stay_neutral(self):
        """
        Aggregate repeated exchange outcomes as observations rather than automatic weaknesses.
        """
        for count, signal in ((2, "favorable_death_exchange"), (0, "unfavorable_death_exchange")):
            report = analyze_player([outcome_game(count, index=i) for i in range(4)])
            with self.subTest(signal=signal):
                pattern = next(p for p in report["patterns"] if p["type"] == signal)
                self.assertEqual(pattern["games_with_pattern"], 4)
                self.assertEqual(pattern["valence"], "observation")
                self.assertEqual(report["weakness_trends"], [])

    def test_compact_outcomes_serialize_without_raw_timeline(self):
        """
        Retain outcome context in serializable analysis without exporting frame payloads.
        """
        game = json.loads(json.dumps(outcome_game(2)))
        self.assertIn("death_outcome", game["deaths"][0])
        self.assertNotIn("participantFrames", json.dumps(game))
        self.assertNotIn("frames", game)


class SpendingThresholdTests(unittest.TestCase):
    def test_all_requested_role_boundaries(self):
        """
        Apply every specified role threshold to spent gold while retaining the raw unspent measurement.
        """
        cases = [
            ("TOP", 19500, 3000, False),
            ("TOP", 20000, 3000, True),
            ("MIDDLE", 20500, 4000, True),
            ("JUNGLE", 20000, 2500, True),
            ("BOTTOM", 22500, 3000, False),
            ("BOTTOM", 23000, 3000, True),
            ("UTILITY", 11500, 2000, False),
            ("UTILITY", 12000, 2000, True),
        ]
        for role, spent, unspent, suppressed in cases:
            with self.subTest(role=role, spent=spent):
                game = outcome_game(role=role, spent=spent, unspent=unspent)
                death = game["deaths"][0]
                context = death["unspent_gold_context"]
                self.assertEqual(has_effectively_completed_build(role, spent), suppressed)
                self.assertEqual(context["total_gold_spent"], spent)
                self.assertEqual(context["suppress_unspent_gold_coaching"], suppressed)
                self.assertEqual(death["state_before_death"]["current_gold"], unspent)
                kinds = {c["type"] for c in death["cause_candidates"]}
                self.assertEqual("large_unspent_gold" in kinds, not suppressed)
                self.assertEqual(game["aggregate_metrics"]["large_unspent_gold_deaths"], int(not suppressed))
                self.assertEqual(game["weakness_signals"], [])
                self.assertIn("not_proof_of_full_inventory", context["interpretation"])

    def test_current_gold_does_not_determine_spending_threshold(self):
        """
        Use total gold minus current gold rather than total earned or current unspent gold as spending.
        """
        context = unspent_gold_context("BOTTOM", {"total_gold": 24000, "current_gold": 4000})
        self.assertEqual(context["total_gold_spent"], 20000)
        self.assertFalse(context["threshold_reached"])
        context = unspent_gold_context("BOTTOM", {"total_gold": 27000, "current_gold": 3200})
        self.assertEqual(context["total_gold_spent"], 23800)
        self.assertTrue(context["suppress_unspent_gold_coaching"])
        self.assertNotIn("inventory_full", context)

    def test_unknown_role_or_spending_does_not_invent_purchase_opportunity(self):
        """
        Suppress spending advice when the threshold comparison itself is unavailable.
        """
        for role, state in (
            ("UNKNOWN", {"total_gold": 25000, "current_gold": 3000}),
            ("BOTTOM", {}),
            ("BOTTOM", {"total_gold": 1000, "current_gold": 3000}),
        ):
            with self.subTest(role=role, state=state):
                context = unspent_gold_context(role, state)
                self.assertTrue(context["suppress_unspent_gold_coaching"])
                self.assertIsNone(context["threshold_reached"])

    def test_legacy_gold_occurrences_are_rechecked_before_aggregation(self):
        """
        Prevent old cached gold signals from reappearing after the role spending threshold.
        """
        games = [outcome_game(role="BOTTOM", spent=23800, unspent=3200, index=i) for i in range(4)]
        for game in games:
            game["aggregate_metrics"]["large_unspent_gold_deaths"] = 1
            game["pattern_occurrences"].append(
                {
                    "type": "large_unspent_gold",
                    "timestamp": DEATH_TIME,
                    "game_phase": "MID_GAME",
                    "valence": "weakness_candidate",
                    "evidence": {},
                }
            )
        original = copy.deepcopy(games)
        report = analyze_player(games)
        self.assertEqual(report["aggregate_metrics"]["large_unspent_gold_deaths"]["mean"], 0)
        self.assertFalse(any(p["type"] == "large_unspent_gold" for p in report["patterns"]))
        self.assertEqual(report["weakness_trends"], [])
        self.assertEqual(games, original)

    def test_below_threshold_recurring_gold_is_only_an_observation(self):
        """
        Keep useful below-threshold gold observations without recommending a reset.
        """
        report = analyze_player([outcome_game(spent=22500, unspent=3000, index=i) for i in range(4)])
        pattern = next(p for p in report["patterns"] if p["type"] == "large_unspent_gold")
        self.assertEqual(pattern["valence"], "observation")
        self.assertEqual(report["weakness_trends"], [])


try:
    from google import genai
except ImportError:
    genai = None


@unittest.skipIf(genai is None, "Use the project .venv for actual prompt assembly tests.")
class OutcomePromptTests(unittest.TestCase):
    def test_outcome_priority_gold_suppression_and_no_invented_mechanics(self):
        """
        Verify the actual coaching prompt prioritizes exchange evidence and protects threshold-crossing players.
        """
        source = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location("outcome_prompts_test", source / "prompts.py")
        prompts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prompts)
        client = Mock()
        client.models.generate_content.return_value = types.SimpleNamespace(text="offline")
        with patch.dict(sys.modules, {"app.prompts": prompts}), patch.object(genai, "Client", return_value=client):
            with patch.dict(os.environ, {"GEMINI_API_KEY": "offline"}):
                spec = importlib.util.spec_from_file_location("outcome_gemini_test", source / "gemini.py")
                gemini = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(gemini)
        gemini.ask_gemini(
            user_message="I traded for two kills and stopped dragon.",
            season_knowledge="",
            player_data=None,
            enemy_data=None,
            player_stats=None,
            matchup_stats=None,
            requested_stats={},
            role_rankings=None,
            history=[],
            role=None,
            query_type="general",
            player_analysis=outcome_game(2, spent=23800, unspent=3200),
            player_analysis_mode="specific_game",
        )
        prompt = client.models.generate_content.call_args.kwargs["contents"]
        for text in (
            "A death is not automatically a mistake",
            "Do not invent flank paths, bush positions, rotations",
            "does not prove objective prevention",
            "availability and situational usability are established",
            "Twitch R damage does not establish",
            "Diana/Gwen involvement",
            "user-reported context",
            "Do not criticize unspent gold",
            "do not recommend resetting merely to spend",
            "does NOT establish six completed items",
            "high unspent gold does not by itself prove",
            '"suppress_unspent_gold_coaching": true',
        ):
            self.assertIn(text, prompt)
        self.assertLess(prompt.index("1. Surrounding fight/outcome"), prompt.index("5. Recorded damage evidence"))


if __name__ == "__main__":
    unittest.main()
