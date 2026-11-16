"""Aggregation acceptance tests and mocked Riot orchestration tests."""

import copy
import json
import unittest
from unittest.mock import patch
import requests

from test_player_data import fixture, kill, hit, sample_match
from app.player_data.game_analyser import analyze_game
from app.player_data.timeline_parser import parse_timeline
from app.player_data.player_analyzer import analyze_player, MAX_PATTERN_EXAMPLES, MAX_DEATH_ABILITY_PATTERNS
from app.player_data import analysis_service as service


def game(index=0, champion="Yunara", role="BOTTOM", jungle=False, strength=False):
    """
    Build a synthetic analyzed game for aggregation tests.
    """
    events = [kill(610000, assists=[8])] if jungle else []
    if strength:
        events = [
            kill(610000, killer=1, victim=6, assists=[]),
            kill(620000, killer=1, victim=7, assists=[]),
            {
                "type": "ELITE_MONSTER_KILL",
                "timestamp": 630000,
                "killerId": 1,
                "killerTeamId": 100,
                "monsterType": "DRAGON",
            },
        ]
    raw, match = fixture(events)
    match["match_id"] = f"TEST_{index}"
    match["game_start_timestamp"] = 1700000000000 + index * 3600000
    match["player"]["champion"] = champion
    match["player"]["role"] = role
    return analyze_game(parse_timeline(raw, 1, 6), match)


class AggregationTests(unittest.TestCase):
    def test_structured_only_round_trip_and_averages(self):
        """
        Verify structured only round trip and averages.
        """
        games = [game(1), game(2)]
        games[0]["aggregate_metrics"]["overall_cs_per_min"] = 6
        games[1]["aggregate_metrics"]["overall_cs_per_min"] = 8
        report = analyze_player(json.loads(json.dumps(games)))
        self.assertEqual(report["games_analyzed"], 2)
        self.assertEqual(report["aggregate_metrics"]["overall_cs_per_min"]["mean"], 7)
        self.assertEqual(report["aggregate_metrics"]["engage_cc_deaths"]["samples"], 0)
        self.assertIsNone(report["aggregate_metrics"]["engage_cc_deaths"]["mean"])

    def test_one_jungle_death_is_not_recurring_weakness(self):
        """
        Verify one jungle death is not recurring weakness.
        """
        report = analyze_player([game(jungle=True)])
        self.assertEqual(report["high_confidence_patterns"], [])
        self.assertEqual(report["weakness_trends"], [])
        self.assertEqual(report["cohorts"][0]["patterns"][0]["status"], "limited_observation")

    def test_recurrence_across_games(self):
        """
        Verify recurrence across games.
        """
        report = analyze_player([game(i, jungle=True) for i in range(8)])
        pattern = report["high_confidence_patterns"][0]
        self.assertEqual(pattern["games_with_pattern"], 8)
        self.assertEqual(pattern["eligible_games"], 8)
        self.assertEqual(pattern["type"], "enemy_jungler_involved_in_death")
        self.assertEqual(report["weakness_trends"], [])  # Observation is not tracking blame.

    def test_general_role_pattern_can_span_champions(self):
        """
        Verify general role pattern can span champions.
        """
        report = analyze_player(
            [game(i, champion=champ, jungle=True) for i, champ in enumerate(["Yunara", "Jinx", "Ashe"])]
        )
        pattern = report["low_confidence_patterns"][0]
        self.assertEqual(pattern["games_with_pattern"], 3)
        self.assertEqual(len(pattern["champions_with_pattern"]), 3)
        self.assertEqual(len(report["cohorts"]), 3)

    def test_many_occurrences_one_game_do_not_become_cross_game_trend(self):
        """
        Verify many occurrences one game do not become cross game trend.
        """
        one = game(jungle=True)
        one["pattern_occurrences"] *= 12
        report = analyze_player([one, game(2), game(3)])
        pattern = report["cohorts"][0]["patterns"][0]
        self.assertEqual(pattern["occurrences"], 12)
        self.assertEqual(pattern["games_with_pattern"], 1)
        self.assertEqual(pattern["status"], "limited_observation")

    def test_filter_and_sample_size(self):
        """
        Verify filter and sample size.
        """
        report = analyze_player([game(1), game(2, champion="Ahri"), game(3)], champion="yunara")
        self.assertEqual(report["games_analyzed"], 2)
        self.assertEqual(report["champions_played"], {"Yunara": 2})

    def test_roles_and_queues_not_blindly_pooled(self):
        """
        Verify roles and queues not blindly pooled.
        """
        report = analyze_player([game(1), game(2, role="UTILITY")])
        self.assertEqual(report["aggregate_metrics"], {})
        self.assertEqual(len(report["cohorts"]), 2)

    def test_strengths_do_not_depend_on_win(self):
        """
        Verify strengths do not depend on win.
        """
        games = [game(i, strength=True) for i in range(4)]
        report = analyze_player(games)
        self.assertTrue(report["strength_trends"])
        for item in games:
            item["player"]["win"] = False
        loss_report = analyze_player(games)
        self.assertEqual(report["strength_trends"], loss_report["strength_trends"])

    def test_recurring_inferences_retain_limited_confidence(self):
        """
        Verify recurring inferences retain limited confidence.
        """
        games = [game(i) for i in range(4)]
        for item in games:
            item["pattern_occurrences"] = [
                {"type": "possible_isolation", "game_phase": "LANE", "confidence": 0.6, "valence": "weakness_candidate"}
            ]
        report = analyze_player(games)
        self.assertEqual(report["weakness_trends"], [])
        self.assertEqual(report["patterns"][0]["confidence"], 0.6)
        self.assertEqual(report["patterns"][0]["valence"], "observation")

    def test_missing_metrics_dates_duplicates_and_versions(self):
        """
        Verify missing metrics dates duplicates and versions.
        """
        first = game(1)
        second = game(2)
        second["aggregate_metrics"]["matchup_gold_diff_at_10"] = None
        second["game_start_timestamp"] = None
        report = analyze_player([first, first, second])
        self.assertEqual(report["games_analyzed"], 2)
        self.assertEqual(report["duplicate_games_ignored"], 1)
        self.assertEqual(report["aggregate_metrics"]["matchup_gold_diff_at_10"]["samples"], 1)
        self.assertEqual(report["date_range"]["games_with_dates"], 1)
        second["analysis_version"] = "old"
        with self.assertRaises(ValueError):
            analyze_player([first, second])

    def test_compact_report_and_chronology(self):
        """
        Verify compact report and chronology.
        """
        games = [game(i, jungle=True) for i in range(20)]
        report = analyze_player(list(reversed(games)))
        self.assertLess(len(json.dumps(report)), len(json.dumps(games)) / 2)
        self.assertEqual(report["date_range"]["start_ms"], games[0]["game_start_timestamp"])
        self.assertTrue(report["cohorts"][0]["metric_direction"])
        self.assertEqual(analyze_player([])["games_analyzed"], 0)

    def test_duplicate_cannot_hide_mixed_players(self):
        """
        Verify duplicate cannot hide mixed players.
        """
        first = game(1)
        second = copy.deepcopy(first)
        second["puuid"] = "another-player"
        with self.assertRaises(ValueError):
            analyze_player([first, second])

    def test_empty_timeline_not_zero_event_measurements(self):
        """
        Verify empty timeline not zero event measurements.
        """
        raw, match = fixture()
        raw["info"]["frames"] = []
        result = analyze_game(parse_timeline(raw, 1, 6), match)
        report = analyze_player([result])
        self.assertEqual(report["aggregate_metrics"]["enemy_jungler_deaths"]["samples"], 0)
        self.assertIsNone(report["aggregate_metrics"]["possible_resource_misses"]["mean"])


class GeminiEvidenceTests(unittest.TestCase):
    def ability_game(self, index=0, death_count=1, champion="Yunara"):
        """
        Build a synthetic game with reported ability damage for tests.
        """
        raw, match = fixture(
            [kill(610000 + i * 120000, sources=[hit(7, "nautilusanchordrag")]) for i in range(death_count)]
        )
        match["match_id"] = f"ABILITY_{index}"
        match["player"]["champion"] = champion
        return analyze_game(parse_timeline(raw, 1, 6), match)

    def test_examples_preserve_evidence_across_distinct_games(self):
        """
        Verify examples preserve evidence across distinct games.
        """
        games = [game(i, jungle=True) for i in range(5)]
        games[0]["pattern_occurrences"] *= 10
        report = analyze_player(games)
        examples = report["patterns"][0]["examples"]
        self.assertEqual(len(examples), MAX_PATTERN_EXAMPLES)
        self.assertEqual(len({e["match_id"] for e in examples}), MAX_PATTERN_EXAMPLES)
        self.assertEqual(examples[0]["evidence"], games[0]["pattern_occurrences"][0]["evidence"])
        self.assertIn("timestamp", examples[0])
        self.assertIn("champion", examples[0])
        self.assertNotIn("deaths", examples[0])
        self.assertNotIn("aggregate_metrics", examples[0])
        self.assertNotIn("confidence", examples[0])  # Factual source gains no invented confidence.

    def test_inference_example_confidence_and_no_input_mutation(self):
        """
        Verify inference example confidence and no input mutation.
        """
        games = [game(i) for i in range(4)]
        for g in games:
            g["pattern_occurrences"] = [
                {
                    "type": "possible_low_health_exposure",
                    "game_phase": "LANE",
                    "confidence": 0.6,
                    "valence": "weakness_candidate",
                    "timestamp": 939000,
                    "evidence": {"sampled_health_ratio": 0.3},
                }
            ]
        report = analyze_player(games)
        self.assertEqual(report["weakness_trends"], [])
        example = report["patterns"][0]["examples"][0]
        self.assertEqual(example["confidence"], 0.6)
        example["evidence"]["sampled_health_ratio"] = 0
        self.assertEqual(games[0]["pattern_occurrences"][0]["evidence"]["sampled_health_ratio"], 0.3)

    def test_five_deaths_four_games_and_duplicate_hits(self):
        """
        Verify five deaths four games and duplicate hits.
        """
        games = [self.ability_game(0, 2)] + [self.ability_game(i) for i in range(1, 4)]
        games[0]["deaths"][0]["ability_hits"] *= 2
        pattern = analyze_player(games)["death_ability_patterns"][0]
        self.assertEqual(pattern["death_occurrences"], 5)
        self.assertEqual(pattern["games_with_occurrence"], 4)
        self.assertEqual(pattern["eligible_games"], 4)
        self.assertEqual(pattern["game_rate"], 1)
        self.assertEqual(len(pattern["example_deaths"]), MAX_PATTERN_EXAMPLES)
        self.assertEqual(len({e["match_id"] for e in pattern["example_deaths"]}), MAX_PATTERN_EXAMPLES)

    def test_multiple_deaths_same_game(self):
        """
        Verify multiple deaths same game.
        """
        report = analyze_player([self.ability_game(death_count=2)])
        pattern = report["death_ability_patterns"][0]
        self.assertEqual(pattern["death_occurrences"], 2)
        self.assertEqual(pattern["games_with_occurrence"], 1)

    def test_conflict_allied_and_unresolved_sources_excluded(self):
        """
        Verify conflict allied and unresolved sources excluded.
        """
        for change in (
            {"attribution_status": "identity_conflict"},
            {"resolved_team_relation": "allied"},
            {"resolved_participant_id": None},
            {"resolved_team_relation": "unknown"},
        ):
            with self.subTest(change=change):
                g = self.ability_game()
                g["deaths"][0]["ability_hits"][0].update(change)
                self.assertEqual(analyze_player([g])["death_ability_patterns"], [])

    def test_kaisa_no_semantic_classification(self):
        """
        Verify kaisa no semantic classification.
        """
        raw, match = fixture([kill(sources=[hit(6, "kaisaq")])])
        g = analyze_game(parse_timeline(raw, 1, 6), match)
        pattern = analyze_player([g])["death_ability_patterns"][0]
        self.assertEqual(pattern["spell_name"], "kaisaq")
        self.assertNotIn("confidence", pattern)
        self.assertNotIn("engage", pattern)
        self.assertNotIn("cause_candidates", pattern)
        self.assertEqual(g["deaths"][0]["important_spell_hits"], [])
        self.assertIsNone(g["aggregate_metrics"]["engage_cc_deaths"])

    def test_empty_abilities_and_no_timeline_have_explicit_coverage(self):
        """
        Verify empty abilities and no timeline have explicit coverage.
        """
        g = self.ability_game()
        g["deaths"][0]["ability_hits"] = []
        report = analyze_player([g])
        self.assertEqual(report["death_ability_patterns"], [])
        self.assertEqual(report["death_ability_coverage"]["observed_deaths"], 1)
        self.assertIsNone(report["aggregate_metrics"]["engage_cc_deaths"]["mean"])
        g["timeline_observation_available"] = False
        self.assertEqual(analyze_player([g])["death_ability_coverage"]["eligible_games"], 0)

    def test_champion_filter_and_mixed_role_boundaries(self):
        """
        Verify champion filter and mixed role boundaries.
        """
        games = [self.ability_game(0), self.ability_game(1, champion="Ahri")]
        games[1]["player"]["role"] = "MIDDLE"
        report = analyze_player(games, champion="Yunara")
        self.assertEqual(report["games_analyzed"], 1)
        self.assertEqual(report["death_ability_patterns"][0]["eligible_games"], 1)
        mixed = analyze_player(games)
        self.assertEqual(mixed["death_ability_patterns"], [])
        self.assertEqual(len(mixed["cohorts"]), 2)
        self.assertEqual(mixed["aggregate_metrics"], {})

    def test_ability_limit_roundtrip_and_compact_payload(self):
        """
        Verify ability limit roundtrip and compact payload.
        """
        games = [self.ability_game(i) for i in range(20)]
        one_hit = games[0]["deaths"][0]["ability_hits"][0]
        games[0]["deaths"][0]["ability_hits"] = [
            {**one_hit, "spell_name": f"spell{i}"} for i in range(MAX_DEATH_ABILITY_PATTERNS + 5)
        ]
        report = analyze_player(json.loads(json.dumps(games)))
        self.assertEqual(len(report["death_ability_patterns"]), MAX_DEATH_ABILITY_PATTERNS)
        self.assertGreater(report["death_ability_coverage"]["patterns_omitted"], 0)
        self.assertEqual(report, json.loads(json.dumps(report)))
        self.assertLess(len(json.dumps(report)), len(json.dumps(games)) / 2)
        self.assertNotIn("game_analyses", report)
        self.assertNotIn("windows", games[0])
        self.assertEqual(report["analysis_version"], "4")
        self.assertEqual(games[0]["schema_version"], 2)

    def test_spell_case_normalization_and_duplicate_death_object(self):
        """
        Verify spell case normalization and duplicate death object.
        """
        g = self.ability_game()
        extra = copy.deepcopy(g["deaths"][0]["ability_hits"][0])
        extra["spell_name"] = "NautilusAnchorDrag"
        extra["spell_slot"] = 3
        g["deaths"][0]["ability_hits"].append(extra)
        g["deaths"].append(copy.deepcopy(g["deaths"][0]))
        pattern = analyze_player([g])["death_ability_patterns"][0]
        self.assertEqual(pattern["death_occurrences"], 1)
        self.assertEqual(pattern["spell_slots"], [0, 3])

    def test_version_three_requires_regeneration(self):
        """
        Verify version three requires regeneration.
        """
        g = game()
        g["analysis_version"] = "3"
        with self.assertRaises(ValueError):
            analyze_player([g])


class ServiceTests(unittest.TestCase):
    def test_history_exhausted_and_invalid_request(self):
        """
        Verify history exhausted and invalid request.
        """
        with patch.object(service.riot_api, "get_recent_match_ids", return_value=[]):
            report = service.analyze_champion("1", "Yunara", 20)
        self.assertEqual(report["games_analyzed"], 0)
        self.assertEqual(report["retrieval"]["stop_reason"], "history_exhausted")
        with self.assertRaises(ValueError):
            service.analyze_recent_games("1", game_count=0)

    def test_rate_limit_stops_without_partial_report(self):
        """
        Propagate Riot's typed rate limit instead of returning partial coaching evidence.
        """
        error = service.RiotRateLimitError(retry_after=12)
        with patch.object(service.riot_api, "get_recent_match_ids", return_value=["TEST"]), patch.object(
            service.riot_api, "get_match", side_effect=error
        ):
            with self.assertRaises(service.RiotRateLimitError) as raised:
                service.analyze_recent_games("1")
        self.assertIs(raised.exception, error)

    def test_riot_pagination_parameters(self):
        """
        Verify riot pagination parameters.
        """
        response = unittest.mock.Mock()
        response.json.return_value = ["TEST"]
        with patch.object(service.riot_api, "RIOT_API_KEY", "test-key"), patch.object(
            service.riot_api.requests, "get", return_value=response
        ) as request:
            service.riot_api.get_recent_match_ids("1", count=20, start=50)
        self.assertEqual(request.call_args.kwargs["params"], {"start": 50, "count": 20})

    def test_twenty_champion_games_search_beyond_twenty_overall(self):
        """
        Verify twenty champion games search beyond twenty overall.
        """
        ids = [f"M_{i}" for i in range(100)]

        def fetch_match(mid, **kwargs):
            """
            Return a mocked match payload for the requested match ID.
            """
            raw = sample_match()
            raw["info"]["gameVersion"] = "16.18"
            raw["metadata"]["matchId"] = mid
            raw["info"]["participants"][0]["championName"] = "Yunara" if int(mid[2:]) % 3 == 0 else "Ahri"
            return raw

        raw_timeline, _ = fixture()
        with patch.object(
            service.riot_api,
            "get_recent_match_ids",
            side_effect=lambda puuid, count, start=0, **kw: ids[start : start + count],
        ) as fetch_ids, patch.object(service.riot_api, "get_match", side_effect=fetch_match), patch.object(
            service.riot_api, "get_match_timeline", return_value=raw_timeline
        ) as timeline:
            report = service.analyze_champion("1", "Yunara", 20)
        self.assertEqual(report["games_analyzed"], 20)
        self.assertEqual(report["retrieval"]["matches_scanned"], 58)
        self.assertEqual(fetch_ids.call_count, 2)
        self.assertEqual(timeline.call_count, 20)

    def test_scan_limit_reports_partial_sample(self):
        """
        Verify scan limit reports partial sample.
        """
        raw = sample_match()
        raw["info"]["gameVersion"] = "16.18"
        raw_timeline, _ = fixture()

        def fetch(mid, **kw):
            """
            Return mocked match data for the service test.
            """
            match = copy.deepcopy(raw)
            match["metadata"]["matchId"] = mid
            return match

        with patch.object(service.riot_api, "get_recent_match_ids", return_value=["a", "b"]), patch.object(
            service.riot_api, "get_match", side_effect=fetch
        ), patch.object(service.riot_api, "get_match_timeline", return_value=raw_timeline):
            report = service.analyze_recent_games("1", 20, max_matches_scanned=2)
        self.assertEqual(report["games_analyzed"], 2)
        self.assertFalse(report["retrieval"]["complete"])
        self.assertEqual(report["retrieval"]["stop_reason"], "scan_limit_reached")

    def test_specific_latest_game_uses_shared_analyzer(self):
        """
        Verify specific latest game uses shared analyzer.
        """
        raw_timeline, _ = fixture()
        raw = sample_match()
        raw["info"]["gameVersion"] = "16.18"
        with patch.object(service.riot_api, "get_recent_match_ids", return_value=["TEST"]), patch.object(
            service.riot_api, "get_match", return_value=raw
        ), patch.object(service.riot_api, "get_match_timeline", return_value=raw_timeline):
            report = service.analyze_specific_game("1")
        self.assertEqual(report["match_id"], "TEST")
        self.assertIn("pattern_occurrences", report)


if __name__ == "__main__":
    unittest.main()
