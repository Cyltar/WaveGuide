"""Offline queue allowlist, selection and Swiftplay regression coverage."""

import unittest
from unittest.mock import patch
from test_specific_match import candidate
import test_specific_match as selector_tests
from app.player_data import analysis_service as service
from app.player_data.game_analyser import analyze_game
from app.player_data.match_parser import parse_match
from app.player_data.timeline_parser import parse_timeline
from app.player_data.player_analyzer import analyze_player
from test_player_data import fixture


def queued(index, queue, **kwargs):
    """
    Build a current-season metadata record with an explicit queue.
    """
    match = candidate(index, **kwargs)
    match["info"]["queueId"] = queue
    return match


class QueueTests(unittest.TestCase):
    setUp = selector_tests.SpecificMatchTests.setUp
    page = selector_tests.SpecificMatchTests.page
    metadata = selector_tests.SpecificMatchTests.metadata

    def test_allowlist_and_direct_guard(self):
        """
        Accept exactly the four requested queues and reject all other modes before timelines.
        """
        for queue in [400, 420, 440, 480]:
            with self.subTest(queue=queue):
                report = service.analyze_loaded_match(queued(1, queue), "1", "americas")
                self.assertEqual(report["queue_id"], queue)
                self.assertEqual(report["queue_name"], service.SUPPORTED_ANALYSIS_QUEUES[queue])
        self.assertEqual(self.timeline.call_count, 4)
        self.timeline.reset_mock()
        for queue in [430, 450, 490, 700, 900, 1010, 1700, 1900, 0, 830, 840, 850, 2000, 9999,
                      None, "420", 420.0, True, []]:
            with self.subTest(queue=queue):
                match = queued(1, queue)
                self.assertFalse(service.is_supported_analysis_match(match))
                with self.assertRaises(service.UnsupportedAnalysisQueueError):
                    service.analyze_loaded_match(match, "1", "americas")
        self.assertFalse(service.is_supported_analysis_match({"info": {"mapId": 11}}))
        self.timeline.assert_not_called()

    def test_recent_games_skip_and_count(self):
        """
        Continue past unsupported modes and fetch only the requested eligible timelines.
        """
        self.matches = [queued(i, q) for i, q in enumerate([450, 400, 1700, 420, 900, 480, 440], 1)]
        report = service.analyze_recent_games("1", 4)
        retrieval = report["retrieval"]
        self.assertEqual((report["games_analyzed"], retrieval["matches_scanned"],
                          retrieval["matching_matches_found"], retrieval["unsupported_matches_skipped"]), (4, 7, 4, 3))
        self.assertEqual(retrieval["supported_queue_ids"], [400, 420, 440, 480])
        self.assertEqual(retrieval["unsupported_queue_counts"], {"450": 1, "1700": 1, "900": 1})
        self.assertEqual([call.args[0] for call in self.timeline.call_args_list], ["NA1_2", "NA1_4", "NA1_6", "NA1_7"])

    def test_champion_and_ordinal_ignore_unsupported_matches(self):
        """
        Count only eligible champion matches for collection and ordinal selection.
        """
        self.matches = [queued(i, q, champion=c) for i, (q, c) in enumerate(
            [(450, "Yunara"), (400, "Yunara"), (1700, "Yunara"), (420, "Yunara"),
             (400, "Xayah"), (480, "Yunara")], 1)]
        report = service.analyze_champion("1", "Yunara", 3)
        self.assertEqual(report["games_analyzed"], 3)
        self.assertEqual(report["retrieval"]["matches_scanned"], 6)
        self.timeline.reset_mock()
        report = service.analyze_specific_game("1", champion="Yunara", specific_game_index=3)
        self.assertEqual(report["match_id"], "NA1_6")
        self.assertEqual(report["selection"]["unsupported_matches_skipped"], 2)
        self.timeline.assert_called_once_with("NA1_6", routing_region="americas")

    def test_kda_and_opponent_cannot_create_unsupported_ambiguity(self):
        """
        Discard unsupported matches before KDA, champion or lane-opponent checks.
        """
        self.matches = [queued(1, 450), queued(2, 1700), queued(3, 400),
                        queued(4, 420, opponent="Jinx"), queued(5, 480, kda=(0, 0, 0))]
        self.matches[0]["info"]["participants"] = []
        report = service.analyze_specific_game("1", champion="Yunara", opponent="Kaisa", kills=13, deaths=7, assists=11)
        self.assertEqual(report["match_id"], "NA1_3")
        self.assertEqual(report["selection"]["matching_games_found"], 1)
        self.timeline.assert_called_once_with("NA1_3", routing_region="americas")

    def test_explicit_rejection_has_no_fallback_or_analysis(self):
        """
        Reject an explicit unsupported ID without timelines, analysis or history fallback.
        """
        self.matches = [queued(1, 450)]
        with patch.object(service, "analyze_game") as analyzer:
            with self.assertRaisesRegex(service.UnsupportedAnalysisQueueError, "Swiftplay"):
                service.analyze_specific_game("1", match_id="NA1_1")
            analyzer.assert_not_called()
        self.timeline.assert_not_called()
        self.ids.assert_not_called()

    def test_season_precedes_queue_and_stops_scanning(self):
        """
        Skip current-season ARAM but stop at the old season before counting its queue.
        """
        self.matches = [queued(1, 400), queued(2, 450), queued(3, 420), queued(4, 450, season="15.1"), queued(5, 440)]
        for method in (lambda: service.analyze_recent_games("1", 5)["retrieval"],
                       lambda: service.find_specific_match("1", specific_game_index=5)):
            try:
                metadata = method()
            except service.SpecificMatchNotFoundError as error:
                metadata = error.selection
                self.assertIn("only 2 supported current-season", str(error))
            self.assertEqual(metadata["matches_scanned"], 4)
            self.assertEqual(metadata["unsupported_matches_skipped"], 1)
            self.assertEqual(metadata["stop_reason"], "current_season_exhausted")
        with self.assertRaisesRegex(ValueError, "not from the current season"):
            service.analyze_specific_game("1", match_id="NA1_4")

    def test_scan_budget_and_empty_eligible_history(self):
        """
        Respect the scan budget even when every inspected match is unsupported.
        """
        self.matches = [queued(i, 450) for i in range(1, 5)]
        report = service.analyze_recent_games("1", 3, max_matches_scanned=2)
        self.assertEqual(report["games_analyzed"], 0)
        self.assertEqual(report["retrieval"]["matches_scanned"], 2)
        self.assertEqual(report["retrieval"]["unsupported_matches_skipped"], 2)
        self.assertEqual(report["retrieval"]["stop_reason"], "scan_limit_reached")
        with self.assertRaisesRegex(service.SpecificMatchNotFoundError, "supported current-season Yunara"):
            service.find_specific_match("1", champion="Yunara")
        self.timeline.assert_not_called()

    def test_swiftplay_context_and_cohorts(self):
        """
        Preserve queue boundaries and omit uncalibrated Swiftplay timing estimates.
        """
        reports = [service.analyze_loaded_match(queued(i, q), "1", "americas") for i, q in [(1, 420), (2, 480)]]
        swift = reports[1]
        self.assertIsNone(swift["cs_analysis"]["estimated_lane_waves"])
        self.assertIsNone(swift["cs_analysis"]["lane_cs_per_wave"])
        self.assertIsNotNone(swift["cs_analysis"]["overall_cs_per_min"])
        self.assertEqual(swift["farm_windows"], [])
        self.assertEqual(swift["major_swings"], [])
        for key in ("unexplained_low_farm_windows", "teammate_absorption_windows", "major_economic_swings"):
            self.assertIsNone(swift["aggregate_metrics"][key])
        aggregate = analyze_player(reports)
        self.assertEqual({c["queue_id"] for c in aggregate["cohorts"]}, {420, 480})
        self.assertEqual(aggregate["aggregation_scope"], "use_separate_cohorts")
        self.assertTrue(any("Swiftplay" in note for note in aggregate["limitations"]))

    def test_direct_analyzer_cannot_bypass_allowlist(self):
        """
        Guard standalone deterministic analysis as well as service entry points.
        """
        raw, _ = fixture()
        with self.assertRaises(service.UnsupportedAnalysisQueueError):
            analyze_game(parse_timeline(raw, 1, 6), parse_match(queued(1, 450), "1"))


if __name__ == "__main__":
    unittest.main()
