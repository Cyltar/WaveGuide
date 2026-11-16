"""Offline regressions for sparse death-evidence boundaries and legacy aggregation."""

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
from app.player_data.game_analyser import analyze_game, analyze_death
from app.player_data.player_analyzer import analyze_player
from app.player_data.timeline_parser import parse_timeline
from test_player_data import fixture, kill, hit


def death_fixture(timestamp=902000, health=28, gold=2437, ally_distance=760):
    """
    Build a death after a low-health snapshot with Lulu nearby and an independently located death event.
    """
    sources = [hit(7, "nautilusanchordrag", 100), hit(6, "kaisaq", 200), hit(6, "kaisaq", 300)]
    raw, match = fixture([kill(timestamp, assists=[7, 8], sources=sources, x=9000, y=9000)])
    match["participant_info"][2]["champion"] = "Lulu"
    match["player"]["champion"] = "Xayah"
    snapshot = raw["info"]["frames"][15]["participantFrames"]
    snapshot["1"]["championStats"]["health"] = health
    snapshot["1"]["currentGold"] = gold
    snapshot["2"]["position"] = {"x": 5000 + ally_distance, "y": 5000}
    return raw, match


def report_for(raw, match):
    """
    Analyze a synthetic match without external services.
    """
    return analyze_game(parse_timeline(raw, 1, 6), match)


class DeathSnapshotTests(unittest.TestCase):
    def test_lulu_distance_uses_same_frame_not_death_position(self):
        """
        Keep Lulu's historical 760-unit distance and the snapshot's exact age.
        """
        game = report_for(*death_fixture())
        death = game["deaths"][0]
        proximity = death["proximity_snapshot"]
        self.assertEqual(proximity["snapshot_timestamp"], 900000)
        self.assertEqual(proximity["sample_age_ms"], 2000)
        self.assertEqual(proximity["player_position"], {"x": 5000, "y": 5000})
        self.assertEqual(death["position"], {"x": 9000, "y": 9000})
        self.assertEqual(proximity["allies"], [{"participant_id": 2, "champion": "Lulu", "distance": 760}])
        self.assertEqual(death["nearby_allies"], proximity["allies"])
        self.assertIn("historical_snapshot_only", proximity["interpretation"])
        self.assertIn("death_time_ally_distance", death["unknowns"])
        self.assertEqual(game["weakness_signals"], [])

    def test_stale_positions_are_unknown_but_measurements_survive(self):
        """
        Preserve stale historical distances without presenting them as reliable encounter proximity.
        """
        death = report_for(*death_fixture(timestamp=938000))["deaths"][0]
        self.assertIsNone(death["nearby_allies"])
        self.assertEqual(death["proximity_snapshot"]["sample_age_ms"], 38000)
        self.assertEqual(death["proximity_snapshot"]["historical_observed_allies"][0]["distance"], 760)
        self.assertEqual(death["state_before_death"]["health"], 28)
        self.assertEqual(death["state_before_death"]["sample_status"], "stale_historical_snapshot")
        self.assertEqual(death["cause_candidates"], [])

    def test_missing_ally_position_is_not_observed_absence(self):
        """
        Distinguish unavailable allied positions from a complete snapshot with no nearby allies.
        """
        raw, match = death_fixture()
        raw["info"]["frames"][15]["participantFrames"]["2"]["position"] = None
        death = report_for(raw, match)["deaths"][0]
        self.assertIsNone(death["nearby_allies"])
        self.assertEqual(death["proximity_snapshot"]["ally_status"], "incomplete_snapshot")
        self.assertFalse(any("proximity" in c["type"] for c in death["cause_candidates"]))

    def test_missing_participant_and_unknown_alive_state_are_unknown(self):
        """
        Avoid interpreting missing participant coverage or unknown health as absence.
        """
        for missing in ("participant", "alive"):
            raw, match = death_fixture()
            participants = raw["info"]["frames"][15]["participantFrames"]
            if missing == "participant":
                del participants["2"]
            else:
                participants["2"]["championStats"] = {}
            with self.subTest(missing=missing):
                self.assertIsNone(report_for(raw, match)["deaths"][0]["nearby_allies"])

    def test_partial_coverage_retains_known_lulu_distance(self):
        """
        Retain known measurements while marking incomplete absence evidence as unavailable.
        """
        raw, match = death_fixture()
        del raw["info"]["frames"][15]["participantFrames"]["3"]
        death = report_for(raw, match)["deaths"][0]
        self.assertIsNone(death["nearby_allies"])
        self.assertEqual(death["proximity_snapshot"]["historical_observed_allies"][0]["champion"], "Lulu")

    def test_missing_player_position_or_frame_is_unknown(self):
        """
        Emit null proximity when its reference position or timeline frame is unavailable.
        """
        raw, match = death_fixture()
        raw["info"]["frames"][15]["participantFrames"]["1"]["position"] = None
        self.assertIsNone(report_for(raw, match)["deaths"][0]["nearby_allies"])
        timeline = parse_timeline(raw, 1, 6)
        timeline["frames"] = []
        event = next(e for e in timeline["events"] if e["type"] == "CHAMPION_KILL")
        death = analyze_death(event, timeline, match)
        self.assertIsNone(death["nearby_allies"])
        self.assertIsNone(death["proximity_snapshot"]["snapshot_timestamp"])
        self.assertIsNone(death["state_before_death"])

    def test_complete_empty_snapshot_is_neutral_not_isolation(self):
        """
        Preserve the absence of qualifying allies only as a historical snapshot observation.
        """
        game = report_for(*death_fixture(ally_distance=5000))
        death = game["deaths"][0]
        self.assertEqual(death["nearby_allies"], [])
        observation = next(c for c in death["cause_candidates"] if c["type"] == "limited_allied_proximity_in_last_snapshot")
        self.assertEqual(observation["valence"], "observation")
        self.assertIn("isolation_positioning_error_and_peel_quality_not_established", observation["interpretation"])
        self.assertEqual(game["weakness_signals"], [])
        self.assertIsNone(game["aggregate_metrics"]["possible_isolation_deaths"])
        self.assertEqual(game["aggregate_metrics"]["limited_allied_proximity_in_last_snapshot_deaths"], 1)

    def test_multiple_attackers_do_not_imply_isolation(self):
        """
        Keep several combat contributors independent from sampled ally proximity.
        """
        game = report_for(*death_fixture(health=700, gold=500))
        death = game["deaths"][0]
        self.assertEqual(death["attacker_count"], 3)
        self.assertEqual(death["cause_candidates"], [])
        self.assertEqual(game["weakness_signals"], [])

    def test_low_health_and_gold_are_measurements_not_overstay(self):
        """
        Preserve 28 HP and 2,437 gold without diagnosing overstay or fight-entry health.
        """
        game = report_for(*death_fixture())
        death = game["deaths"][0]
        state = death["state_before_death"]
        self.assertEqual((state["health"], state["current_gold"], state["sample_age_ms"]), (28, 2437, 2000))
        self.assertEqual(death["health_ratio_before"], 0.028)
        self.assertEqual({c["type"] for c in death["cause_candidates"]}, {"low_sampled_health", "large_unspent_gold"})
        self.assertTrue(all(c["valence"] == "observation" for c in death["cause_candidates"]))
        self.assertEqual(game["aggregate_metrics"]["large_unspent_gold_deaths"], 1)
        self.assertEqual(game["aggregate_metrics"]["low_sampled_health_deaths"], 1)
        self.assertIn("safe_recall_opportunity", death["unknowns"])
        self.assertIn("fight_entry_health", death["unknowns"])

    def test_full_health_is_not_fight_entry_or_burst(self):
        """
        Retain full sampled health without inferring fight start or burst duration.
        """
        death = report_for(*death_fixture(health=1000, gold=500))["deaths"][0]
        self.assertEqual(death["health_ratio_before"], 1)
        self.assertEqual(death["cause_candidates"], [])
        self.assertIn("not_fight_entry_state", death["state_before_death"]["interpretation"])
        self.assertIn("fight_start_and_duration", death["unknowns"])

    def test_grouped_damage_does_not_count_casts_or_causes(self):
        """
        Preserve grouped Q damage while explicitly leaving cast count and initiation unknown.
        """
        death = report_for(*death_fixture())["deaths"][0]
        ability = next(hit for hit in death["ability_hits"] if hit["spell_name"] == "kaisaq")
        self.assertEqual(ability["damage"], 500)
        self.assertIn("multiple_hits_or_casts", ability["damage_semantics"])
        self.assertIn("does_not_establish_initiation_or_cause", ability["interpretation"])
        self.assertIn("event_timestamp_is_not_cast_time", death["damage_evidence_semantics"])
        self.assertEqual(death["important_spell_hits"], [])

    def test_protection_and_spell_availability_are_unknown(self):
        """
        Do not reconstruct Lulu's protection or Xayah's escape availability from champion identities.
        """
        death = report_for(*death_fixture())["deaths"][0]
        self.assertIn("ally_protection_during_fight", death["unknowns"])
        self.assertIn("spell_availability", death["unknowns"])
        self.assertIn("escape_opportunity", death["unknowns"])
        self.assertEqual(death["personal_outcome"]["decision_quality"], "not_determined")

    def test_unknown_proximity_does_not_become_zero_measurement(self):
        """
        Keep missing snapshot coverage explicit in aggregation denominators.
        """
        game = report_for(*death_fixture(timestamp=938000))
        metrics = game["aggregate_metrics"]
        self.assertIsNone(metrics["limited_allied_proximity_in_last_snapshot_deaths"])
        self.assertEqual(metrics["reliable_ally_proximity_samples"], 0)
        self.assertIsNone(metrics["low_sampled_health_deaths"])

    def test_report_round_trip_preserves_measurements_without_raw_timeline(self):
        """
        Serialize reliable measurements and null proximity using the existing compact report structure.
        """
        game = report_for(*death_fixture())
        saved = json.loads(json.dumps(game))
        self.assertEqual(saved["deaths"][0]["state_before_death"]["current_gold"], 2437)
        self.assertEqual(saved["analysis_version"], "4")
        self.assertEqual(saved["death_evidence_version"], 3)
        self.assertNotIn("frames", saved)
        self.assertNotIn("participantFrames", json.dumps(saved))


class DeathAggregationTests(unittest.TestCase):
    def games(self, **kwargs):
        """
        Build four independent games containing the same historical death observations.
        """
        games = []
        for index in range(4):
            game = report_for(*death_fixture(**kwargs))
            game["match_id"] = f"DEATH_{index}"
            games.append(game)
        return games

    def test_recurring_proximity_low_health_and_gold_remain_observations(self):
        """
        Aggregate useful repeated measurements without producing isolation or overstay weaknesses.
        """
        report = analyze_player(self.games(ally_distance=5000))
        self.assertEqual(report["weakness_trends"], [])
        self.assertEqual(report["cohorts"][0]["weakness_trends"], [])
        patterns = {p["type"]: p for p in report["patterns"]}
        for kind in ("limited_allied_proximity_in_last_snapshot", "low_sampled_health", "large_unspent_gold",
                     "enemy_jungler_involved_in_death"):
            self.assertEqual(patterns[kind]["games_with_pattern"], 4)
            self.assertEqual(patterns[kind]["valence"], "observation")
        self.assertNotIn("possible_overstay", patterns)
        self.assertNotIn("possible_isolation", patterns)

    def test_legacy_labels_cannot_create_weaknesses_or_mutate_input(self):
        """
        Accept old version-4 JSON but downgrade its unsupported causal labels and metrics.
        """
        games = self.games()
        for game in games:
            game.pop("death_evidence_version")
            game["pattern_occurrences"] = [
                {"type": kind, "game_phase": "LANE", "confidence": 0.9, "valence": "weakness_candidate",
                 "evidence": {"sampled_health_ratio": 0.028}}
                for kind in ("possible_isolation", "possible_overstay", "possible_low_health_exposure")
            ]
            game["aggregate_metrics"]["possible_isolation_deaths"] = 3
            game["aggregate_metrics"]["possible_overstay_deaths"] = 2
        original = copy.deepcopy(games)
        report = analyze_player(games)
        self.assertEqual(report["weakness_trends"], [])
        for key in ("possible_isolation_deaths", "possible_overstay_deaths"):
            self.assertIsNone(report["aggregate_metrics"][key]["mean"])
            self.assertEqual(report["aggregate_metrics"][key]["samples"], 0)
        self.assertTrue(all(p["valence"] == "observation" for p in report["patterns"]))
        self.assertTrue(all(p["examples"][0]["valence"] == "observation" for p in report["patterns"]))
        self.assertEqual(games, original)

    def test_death_abilities_keep_counts_and_grouped_damage_semantics(self):
        """
        Keep ability recurrence and example damage while disallowing single-cast or causal interpretations.
        """
        report = analyze_player(self.games())
        pattern = next(p for p in report["death_ability_patterns"] if p["spell_name"] == "kaisaq")
        self.assertEqual(pattern["death_occurrences"], 4)
        self.assertEqual(pattern["games_with_occurrence"], 4)
        self.assertEqual(pattern["example_deaths"][0]["damage"], 500)
        self.assertIn("multiple_hits_or_casts", pattern["damage_semantics"])
        self.assertIn("does_not_establish_initiation_or_cause", pattern["interpretation"])


try:
    from google import genai
except ImportError:
    genai = None


@unittest.skipIf(genai is None, "Use the project .venv for generated-prompt checks.")
class DeathPromptTests(unittest.TestCase):
    def test_actual_coaching_prompt_contains_boundaries_and_user_context(self):
        """
        Verify the assembled coaching prompt carries evidence constraints and user-reported corrections.
        """
        source = Path(__file__).resolve().parent.parent
        prompts_spec = importlib.util.spec_from_file_location("death_prompts_test", source / "prompts.py")
        prompts = importlib.util.module_from_spec(prompts_spec)
        prompts_spec.loader.exec_module(prompts)
        client = Mock()
        client.models.generate_content.return_value = types.SimpleNamespace(text="offline")
        with patch.dict(sys.modules, {"app.prompts": prompts}), patch.object(genai, "Client", return_value=client):
            with patch.dict(os.environ, {"GEMINI_API_KEY": "offline"}):
                spec = importlib.util.spec_from_file_location("death_gemini_test", source / "gemini.py")
                gemini = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(gemini)
        correction = "Lulu was next to me and used shield and ult."
        gemini.ask_gemini(user_message=correction, season_knowledge="", player_data=None, enemy_data=None,
                          player_stats=None, matchup_stats=None, requested_stats={}, role_rankings=None,
                          history=[{"role": "user", "content": correction}], role=None, query_type="general",
                          player_analysis=report_for(*death_fixture()), player_analysis_mode="specific_game")
        prompt = client.models.generate_content.call_args.kwargs["contents"]
        for text in ("ONE historical frame", "null means unavailable", "does not prove overstay",
                     "never fight-entry health", "does not establish a full-health-to-zero burst",
                     "multiple recorded hits/casts", "Missing allied-protection evidence means unknown",
                     "Champion knowledge does not establish spell availability", "USER-REPORTED CONTEXT",
                     "Do not repeat a conflicting snapshot-based claim", correction):
            self.assertIn(text, prompt)


if __name__ == "__main__":
    unittest.main()
