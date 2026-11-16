"""Offline acceptance tests for deterministic specific-game selection."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.player_data import analysis_service as service
from app.player_data.riot_api import RiotRateLimitError
from test_player_data import sample_match, fixture


def candidate(index, champion="Yunara", kda=(13, 7, 11), opponent="Kaisa", season="16.18"):
    """
    Build ordinary match metadata with a known player and lane counterpart.
    """
    match = sample_match()
    match["metadata"]["matchId"] = f"NA1_{index}"
    match["info"]["gameVersion"] = season
    player = match["info"]["participants"][0]
    player["championName"] = champion
    player.update(dict(zip(("kills", "deaths", "assists"), kda)))
    match["info"]["participants"][5]["championName"] = opponent
    return match


class SpecificMatchTests(unittest.TestCase):
    def setUp(self):
        """
        Replace Riot requests with paginated metadata and an offline timeline.
        """
        self.matches = [candidate(i, champion) for i, champion in enumerate(
            ["Xayah", "Yunara", "Ahri", "Yunara", "Xayah", "Yunara"], 1)]
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.ids = self.stack.enter_context(patch.object(service.riot_api, "get_recent_match_ids", side_effect=self.page))
        self.fetch = self.stack.enter_context(patch.object(service.riot_api, "get_match", side_effect=self.metadata))
        self.timeline = self.stack.enter_context(patch.object(service.riot_api, "get_match_timeline", return_value=fixture()[0]))

    def page(self, puuid, routing_region="americas", count=50, start=0):
        """
        Return a bounded newest-first page from the synthetic history.
        """
        return [match["metadata"]["matchId"] for match in self.matches[start:start + count]]

    def metadata(self, match_id, routing_region="americas"):
        """
        Return metadata without simulating any timeline access.
        """
        return next(match for match in self.matches if match["metadata"]["matchId"] == match_id)

    def test_ordinal_counts_only_matching_games(self):
        """
        Select overall and champion-filtered ordinals independently.
        """
        for filters, expected in [({"specific_game_index": 3}, "NA1_3"),
                                  ({"champion": "Yunara", "specific_game_index": 3}, "NA1_6"),
                                  ({"champion": "Yunara", "specific_game_index": 1}, "NA1_2"),
                                  ({"specific_game_index": 2}, "NA1_2")]:
            with self.subTest(filters=filters):
                match, selection = service.find_specific_match("1", **filters)
                self.assertEqual(match["metadata"]["matchId"], expected)
                self.assertEqual(selection["matching_games_found"], filters["specific_game_index"])
        self.timeline.assert_not_called()

    def test_exact_kda_all_filters_and_canonical_names(self):
        """
        Require all supplied filters while supporting KDA without a champion.
        """
        self.matches = [candidate(1, kda=(13, 7, 10)), candidate(2, opponent="Jinx"),
                        candidate(3), candidate(4, "Ahri", kda=(0, 3, 2))]
        for filters, expected in [({"champion": "yunara", "opponent": "Kai'Sa", "kills": 13, "deaths": 7, "assists": 11}, "NA1_3"),
                                  ({"kills": 0, "deaths": 3, "assists": 2}, "NA1_4"),
                                  ({"champion": "Ahri", "kills": 0, "deaths": 3, "assists": 2}, "NA1_4")]:
            with self.subTest(filters=filters):
                match, _ = service.find_specific_match("1", **filters)
                self.assertEqual(match["metadata"]["matchId"], expected)
        self.timeline.assert_not_called()

    def test_wrong_filters_do_not_fall_back(self):
        """
        Return not-found failures rather than analyze a nonmatching latest game.
        """
        for filters in ({"kills": 13, "deaths": 7, "assists": 12}, {"opponent": "Jinx"}, {"champion": "Zeri"}):
            with self.subTest(filters=filters), self.assertRaises(service.SpecificMatchNotFoundError):
                service.analyze_specific_game("1", **filters)
        self.timeline.assert_not_called()

    def test_insufficient_matching_ordinal(self):
        """
        Report the number of matching games when an ordinal exceeds history.
        """
        with self.assertRaises(service.SpecificMatchNotFoundError) as caught:
            service.find_specific_match("1", champion="Yunara", specific_game_index=5)
        self.assertEqual(caught.exception.selection["matching_games_found"], 3)
        self.assertIn("only 3", str(caught.exception))
        self.assertIn("#5", str(caught.exception))

    def test_ambiguity_without_ordinal_and_explicit_disambiguation(self):
        """
        Reject multiple matches unless a matching ordinal is explicitly requested.
        """
        filters = dict(champion="Yunara", kills=13, deaths=7, assists=11)
        with self.assertRaises(service.SpecificMatchAmbiguousError) as caught:
            service.analyze_specific_game("1", **filters)
        self.assertEqual(caught.exception.selection["matching_games_found"], 2)
        self.assertIn("at least 2", str(caught.exception))
        self.timeline.assert_not_called()
        for index, expected in ((1, "NA1_2"), (2, "NA1_4")):
            match, _ = service.find_specific_match("1", specific_game_index=index, **filters)
            self.assertEqual(match["metadata"]["matchId"], expected)

    def test_plain_champion_is_ambiguous(self):
        """
        Do not treat a champion-only selector as a latest-game request.
        """
        with self.assertRaises(service.SpecificMatchAmbiguousError):
            service.find_specific_match("1", champion="Yunara")

    def test_selected_metadata_reused_and_one_timeline(self):
        """
        Fetch only the selected game's timeline without refetching its metadata.
        """
        report = service.analyze_specific_game("1", champion="Yunara", specific_game_index=3)
        self.timeline.assert_called_once_with("NA1_6", routing_region="americas")
        self.assertEqual([call.args[0] for call in self.fetch.call_args_list], [f"NA1_{i}" for i in range(1, 7)])
        self.assertEqual(report["selection"]["matches_scanned"], 6)
        self.assertEqual(report["match_id"], "NA1_6")
        self.assertNotIn("raw_timeline", report)
        self.assertNotIn("matches", report["selection"])

    def test_explicit_id_bypasses_scanning_and_filters(self):
        """
        Give an explicit match ID priority over conflicting selector fields.
        """
        report = service.analyze_specific_game("1", "NA1_3", champion="Yunara", specific_game_index=0)
        self.ids.assert_not_called()
        self.fetch.assert_called_once_with("NA1_3", routing_region="americas")
        self.timeline.assert_called_once_with("NA1_3", routing_region="americas")
        self.assertEqual(report["selection"]["method"], "match_id")

    def test_season_boundary_stops_scanning(self):
        """
        Never select or scan past the first previous-season match.
        """
        self.matches = [candidate(1, "Ahri"), candidate(2, season="15.24"), candidate(3)]
        with self.assertRaises(service.SpecificMatchNotFoundError) as caught:
            service.find_specific_match("1", champion="Yunara")
        self.assertEqual(caught.exception.selection["stop_reason"], "current_season_exhausted")
        self.assertEqual(self.fetch.call_count, 2)
        with self.assertRaisesRegex(ValueError, "current season"):
            service.analyze_specific_game("1", "NA1_2")
        self.timeline.assert_not_called()

    def test_unique_selector_is_verified_to_season_boundary(self):
        """
        Accept one filtered match only after its uniqueness has been established.
        """
        self.matches = [candidate(1), candidate(2, "Ahri"), candidate(3, season="15.24")]
        match, selection = service.find_specific_match("1", champion="Yunara")
        self.assertEqual(match["metadata"]["matchId"], "NA1_1")
        self.assertEqual(selection["matches_scanned"], 3)
        self.assertEqual(selection["stop_reason"], "current_season_exhausted")

    def test_scan_limit_does_not_claim_uniqueness_or_exhaustion(self):
        """
        Reject incomplete searches even when one candidate has already matched.
        """
        for filters in ({"champion": "Ahri"}, {"champion": "Yunara", "specific_game_index": 5}):
            with self.subTest(filters=filters), self.assertRaises(service.SpecificMatchSearchIncompleteError):
                service.find_specific_match("1", max_matches_scanned=3, **filters)
        self.timeline.assert_not_called()

    def test_pagination_and_duplicate_ids_preserve_ordinals(self):
        """
        Continue across pages and count each match only once.
        """
        self.ids.side_effect = [["NA1_1", "NA1_2"], ["NA1_2", "NA1_3"], ["NA1_4", "NA1_5"]]
        with patch.object(service, "MATCH_BATCH_SIZE", 2):
            match, _ = service.find_specific_match("1", champion="Yunara", specific_game_index=2)
        self.assertEqual(match["metadata"]["matchId"], "NA1_4")
        self.assertEqual([call.kwargs["start"] for call in self.ids.call_args_list], [0, 2, 4])
        self.assertEqual(self.fetch.call_count, 4)

    def test_unknown_metadata_never_silently_changes_selection(self):
        """
        Treat unknown season and unknown lane counterparts as incomplete evidence.
        """
        self.matches = [candidate(1, season=None)]
        with self.assertRaises(service.SpecificMatchSearchIncompleteError):
            service.find_specific_match("1")
        self.matches = [candidate(1)]
        self.matches[0]["info"]["participants"][0]["teamPosition"] = ""
        with self.assertRaises(service.SpecificMatchSearchIncompleteError):
            service.find_specific_match("1", opponent="Kaisa", specific_game_index=1)

    def test_invalid_selectors_are_rejected_before_requests(self):
        """
        Validate indexes, complete KDA, champion names, and scan bounds without coercion.
        """
        for filters in ({"specific_game_index": 0}, {"specific_game_index": -1}, {"specific_game_index": True},
                        {"specific_game_index": 1.5}, {"kills": 13}, {"kills": -1, "deaths": 2, "assists": 3},
                        {"champion": "not-a-champion"}, {"opponent": ""}, {"max_matches_scanned": 0}):
            with self.subTest(filters=filters), self.assertRaises(service.SpecificMatchSelectionError):
                service.find_specific_match("1", **filters)
        self.ids.assert_not_called()

    def test_request_failures_propagate_immediately(self):
        """
        Preserve rate limits, authorization failures, and network failures without fallback.
        """
        for error in (RiotRateLimitError(17), requests.ConnectionError("offline"),
                      requests.HTTPError(response=types.SimpleNamespace(status_code=401)),
                      requests.HTTPError(response=types.SimpleNamespace(status_code=403))):
            for target in (self.ids, self.fetch):
                with self.subTest(error=type(error).__name__, target=target):
                    self.ids.side_effect = self.page
                    self.fetch.side_effect = self.metadata
                    target.side_effect = error
                    with self.assertRaises(type(error)) as caught:
                        service.analyze_specific_game("1", champion="Yunara")
                    self.assertIs(caught.exception, error)
        self.timeline.assert_not_called()

    def test_rate_limit_after_one_candidate_does_not_select_it(self):
        """
        Abort uniqueness checking when a later candidate request is rate-limited.
        """
        self.fetch.side_effect = [candidate(1), RiotRateLimitError(9)]
        with self.assertRaises(RiotRateLimitError):
            service.analyze_specific_game("1", champion="Yunara")
        self.assertEqual(self.fetch.call_count, 2)
        self.timeline.assert_not_called()

    def test_empty_history_reports_not_found(self):
        """
        Return a deterministic not-found result when the account has no matches.
        """
        self.matches = []
        with self.assertRaises(service.SpecificMatchNotFoundError):
            service.find_specific_match("1")
        self.fetch.assert_not_called()
        self.timeline.assert_not_called()

    def test_no_filters_preserves_latest_fallback(self):
        """
        Preserve latest-game behavior when the request supplies no selector at all.
        """
        match, selection = service.find_specific_match("1")
        self.assertEqual(match["metadata"]["matchId"], "NA1_1")
        self.assertEqual(selection["effective_game_index"], 1)

    def test_multi_game_limits_and_filters_remain_unchanged(self):
        """
        Keep multi-game collection separate from specific-game ordinal selection.
        """
        with patch.object(service, "analyze_loaded_match", side_effect=lambda match, *args: {"match_id": match["metadata"]["matchId"]}):
            games, retrieval = service.collect_recent_analyses("1", 2, "Yunara", "americas", 200)
        self.assertEqual([game["match_id"] for game in games], ["NA1_2", "NA1_4"])
        self.assertEqual(retrieval["requested_games"], 2)
        with self.assertRaises(ValueError):
            service.collect_recent_analyses("1", 21, None, "americas", 200)


try:
    from google import genai
except ImportError:
    genai = None


def load_source_module(name, filename):
    """
    Load application source with external clients supplied by the test harness.
    """
    path = Path(__file__).resolve().parent.parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(genai is None, "Run with the project's .venv for parser and endpoint tests.")
class SelectorParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        Load the real query parser with an offline Gemini client.
        """
        with patch.object(genai, "Client"):
            cls.parser = load_source_module("selector_query_parser_test", "query_parser.py")

    def parse(self, message, **fields):
        """
        Exercise parser postprocessing using a controlled semantic-extraction result.
        """
        context = self.parser.QueryContext(player_champion=None, enemy_champion=None, role=None, query_type="general",
                                           player_analysis={"requested": True, "mode": "specific_game", **fields})
        with patch.object(self.parser.client.models, "generate_content", return_value=types.SimpleNamespace(parsed=context)):
            return self.parser.parse_query(message).player_analysis

    def test_required_natural_language_examples(self):
        """
        Extract selectors from every required phrase without calling Gemini.
        """
        cases = [
            ("Analyze my 3rd most recent Yunara game.", "Yunara", None, 3, None),
            ("Analyze the Yunara game where I went 13/7/11.", "Yunara", None, None, (13, 7, 11)),
            ("Analyze the Yunara game where I went 13/7/11 against Kaisa.", "Yunara", "Kaisa", None, (13, 7, 11)),
            ("Analyze my most recent Yunara game where I went 13/7/11 against Kaisa.", "Yunara", "Kaisa", 1, (13, 7, 11)),
            ("Analyze my 2nd most recent Yunara game against Kaisa.", "Yunara", "Kaisa", 2, None),
            ("Analyze my previous Yunara game.", "Yunara", None, 2, None),
            ("Analyze my 2/8/4 Ahri game.", "Ahri", None, None, (2, 8, 4)),
            ("Analyze the game where I went 0/3/2.", None, None, None, (0, 3, 2)),
            ("Analyze my recent Yunara game against Kai'Sa.", "Yunara", "Kaisa", 1, None),
            ("Analyze my last Xayah game against Jinx.", "Xayah", "Jinx", 1, None),
            ("Analyze my second most recent Xayah game against Jinx.", "Xayah", "Jinx", 2, None),
            ("Analyze my game before my last game.", None, None, 2, None),
            ("Analyze my fourth most recent game.", None, None, 4, None),
            ("Analyze my 31st most recent game.", None, None, 31, None),
            ("Analyze my twenty-first most recent game.", None, None, 21, None),
            ("Analyze my Yunara game.", "Yunara", None, None, None),
        ]
        for phrase, champion, opponent, index, kda in cases:
            with self.subTest(phrase=phrase):
                result = self.parse(phrase)
                self.assertTrue(result.requested)
                self.assertEqual(result.mode, "specific_game")
                self.assertEqual(result.champion, champion)
                self.assertEqual(result.opponent, opponent)
                self.assertEqual(result.specific_game_index, index)
                self.assertEqual((result.kills, result.deaths, result.assists), kda or (None, None, None))
                self.assertIsNone(result.game_count)

    def test_multi_game_count_is_not_an_ordinal(self):
        """
        Distinguish plural counts from singular matching ordinals.
        """
        for phrase, mode, count, index in [
            ("Analyze my last 3 Yunara games.", "champion_games", 3, None),
            ("Analyze my last 5 games.", "recent_games", 5, None),
            ("Analyze my last game.", "specific_game", None, 1),
            ("Analyze my 3rd most recent Yunara game.", "specific_game", None, 3),
        ]:
            with self.subTest(phrase=phrase):
                result = self.parse(phrase)
                self.assertEqual((result.mode, result.game_count, result.specific_game_index), (mode, count, index))

    def test_no_silent_index_or_name_repair(self):
        """
        Preserve invalid explicit selectors and prevent accidental latest-game defaults.
        """
        self.assertEqual(self.parse("Analyze my 0th most recent game.").specific_game_index, 0)
        self.assertEqual(self.parse("Analyze my -1st most recent game.").specific_game_index, -1)
        self.assertEqual(self.parse("Analyze my zeroth most recent game.").specific_game_index, 0)
        self.assertIsNone(self.parse("Analyze my Yunara game.", specific_game_index=1).specific_game_index)
        self.assertEqual(self.parse("Analyze my UnknownChampion game.", champion="UnknownChampion").champion, "UnknownChampion")
        self.assertEqual(self.parse("Analyze NA1_1234567890.").match_id, "NA1_1234567890")
        self.assertIsNone(self.parse("Analyze my last game.", match_id="NA1_999").match_id)

@unittest.skipIf(genai is None, "Run with the project's .venv for parser and endpoint tests.")
class SelectorAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        Load real endpoint logic while replacing external clients and storage with offline stubs.
        """
        from fastapi import HTTPException
        with patch.object(genai, "Client"):
            cls.parser = load_source_module("selector_endpoint_parser_test", "query_parser.py")
        database = types.ModuleType("app.database")
        names = ["check_daily_ai_request_limit", "create_chat_session", "delete_riot_account", "get_chat_history",
                 "get_champion", "get_riot_account", "get_session_messages", "get_specific_matchup", "get_stats",
                 "get_user_sessions", "record_successful_ai_request", "save_chat_message", "save_riot_account",
                 "user_owns_session"]
        for name in names:
            setattr(database, name, Mock())
        database.HTTPException = HTTPException
        database.requests = requests
        gemini_module = types.ModuleType("app.gemini")
        gemini_module.ask_gemini = Mock(return_value="Offline coaching")
        storage = types.ModuleType("app.supabase_client")
        storage.supabase = Mock()
        storage.create_user_client = Mock()
        with patch.dict(sys.modules, {"app.database": database, "app.gemini": gemini_module,
                                     "app.supabase_client": storage, "app.query_parser": cls.parser}):
            cls.app = load_source_module("selector_endpoint_test", "app.py")

    def setUp(self):
        """
        Isolate endpoint dependencies while keeping real selector dispatch and sanitization.
        """
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.context = self.parser.QueryContext(player_champion=None, enemy_champion=None, role=None,
                                               query_type="general", player_analysis={"requested": True,
                                               "mode": "specific_game", "champion": "Yunara"})
        defaults = {
            "parse_query": self.context, "create_user_client": Mock(), "check_daily_ai_request_limit": None,
            "user_owns_session": True, "get_chat_history": [], "create_chat_session": "session",
            "save_chat_message": None, "record_successful_ai_request": None, "get_champion": {},
            "load_relevant_knowledge": "", "get_riot_account": {"riot_puuid": "1", "routing_region": "americas"},
            "ask_gemini": "Offline coaching",
        }
        self.mocks = {name: self.stack.enter_context(patch.object(self.app, name, return_value=value))
                      for name, value in defaults.items()}
        self.stack.enter_context(patch.object(service.riot_api, "get_account_by_riot_id", return_value={"puuid": "1", "gameName": "Cessereendya", "tagLine": "7944"}))
        self.ids = self.stack.enter_context(patch.object(service.riot_api, "get_recent_match_ids"))
        self.fetch = self.stack.enter_context(patch.object(service.riot_api, "get_match"))
        self.timeline = self.stack.enter_context(patch.object(service.riot_api, "get_match_timeline", return_value=fixture()[0]))
        self.auth = self.app.AuthenticatedUser(user_id="user", access_token="offline-token")

    def chat(self):
        """
        Invoke the real chat endpoint directly without network or database access.
        """
        return self.app.chat(self.app.ChatRequest(message="Analyze my Yunara game."), self.auth)

    def test_selector_errors_return_before_coaching(self):
        """
        Convert ambiguity, not-found, and incomplete search into deterministic responses.
        """
        for matches, phrase in [([candidate(1), candidate(2)], "at least 2"),
                                ([candidate(1, "Ahri")], "couldn't find"),
                                ([candidate(1, season=None)], "couldn't verify")]:
            with self.subTest(phrase=phrase):
                self.ids.return_value = [match["metadata"]["matchId"] for match in matches]
                self.fetch.side_effect = matches
                response = self.chat()
                self.assertIn(phrase, response.answer)
        self.mocks["ask_gemini"].assert_not_called()
        self.timeline.assert_not_called()
        self.mocks["record_successful_ai_request"].assert_not_called()

    def test_unsupported_queue_returns_without_coaching(self):
        """
        Reject explicit unsupported IDs deterministically without timeline or coaching requests.
        """
        self.context.player_analysis.match_id = "NA1_1"
        match = candidate(1)
        match["info"]["queueId"] = 450
        self.fetch.return_value = match
        response = self.chat()
        self.assertIn("does not currently analyze", response.answer)
        self.assertIn("Swiftplay", response.answer)
        self.timeline.assert_not_called()
        self.ids.assert_not_called()
        self.mocks["ask_gemini"].assert_not_called()

    def test_no_supported_games_returns_without_coaching(self):
        """
        Explain empty eligible histories for recent and champion requests without Gemini.
        """
        for mode, champion in [("recent_games", None), ("champion_games", "Yunara")]:
            with self.subTest(mode=mode):
                self.context.player_analysis.mode = mode
                self.context.player_analysis.champion = champion
                self.context.player_analysis.game_count = 3
                self.ids.return_value = ["NA1_1"]
                match = candidate(1)
                match["info"]["queueId"] = 450
                self.fetch.return_value = match
                response = self.chat()
                self.assertIn("supported current-season", response.answer)
                self.assertIn("Swiftplay", response.answer)
                if champion:
                    self.assertIn(champion, response.answer)
        self.timeline.assert_not_called()
        self.mocks["ask_gemini"].assert_not_called()

    def test_rate_limit_returns_retry_after_without_coaching(self):
        """
        Propagate scanning rate limits into the existing retry message before coaching.
        """
        self.ids.return_value = ["NA1_1", "NA1_2"]
        self.fetch.side_effect = RiotRateLimitError(23)
        response = self.chat()
        self.assertIn("23", response.answer)
        self.assertEqual(self.fetch.call_count, 1)
        self.mocks["ask_gemini"].assert_not_called()
        self.timeline.assert_not_called()

    def test_selected_report_only_reaches_coaching(self):
        """
        Send only sanitized analysis of the selected match to the coaching model.
        """
        self.context.player_analysis.specific_game_index = 1
        self.ids.return_value = ["NA1_1", "NA1_2"]
        self.fetch.side_effect = [candidate(1, "Ahri"), candidate(2)]
        response = self.chat()
        self.assertEqual(response.answer, "Offline coaching")
        self.timeline.assert_called_once_with("NA1_2", routing_region="americas")
        self.assertEqual(self.fetch.call_count, 2)
        evidence = self.mocks["ask_gemini"].call_args.kwargs["player_analysis"]
        self.assertEqual(evidence["match_id"], "NA1_2")
        self.assertEqual(evidence["selection"]["matches_scanned"], 2)
        import json
        serialized = json.dumps(evidence)
        for private in ('"puuid"', '"riot_id"', '"participantFrames"', '"victimDamageReceived"', 'NA1_1'):
            self.assertNotIn(private, serialized)
        self.assertNotIn("frames", evidence)
        self.assertNotIn("matches", evidence["selection"])

    def test_current_chat_riot_id_reuse_and_new_chat_isolation(self):
        """
        Reuse only user-supplied Riot IDs in the same chat before linked-account fallback.
        """
        history = [{"role": "user", "content": "Analyze my games, my Riot ID is Cessereendya#7944."},
                   {"role": "assistant", "content": "SomeoneElse#9999"}]
        self.mocks["get_riot_account"].return_value = None
        account = self.app.resolve_player_riot_account(self.context, Mock(), "user", history)
        self.assertEqual(account["riot_puuid"], "1")
        service.riot_api.get_account_by_riot_id.assert_called_once()
        self.mocks["get_riot_account"].assert_not_called()
        self.assertIsNone(self.app.resolve_player_riot_account(self.context, Mock(), "user", []))
        self.mocks["get_riot_account"].assert_called_once()

    def test_dispatch_forwards_every_selector(self):
        """
        Forward all specific-game fields without overloading multi-game counts.
        """
        request = self.context.player_analysis
        request.opponent = "Kaisa"
        request.kills, request.deaths, request.assists = 13, 7, 11
        request.specific_game_index = 3
        with patch.object(self.app, "analyze_specific_game", return_value={}) as analyze:
            self.app.run_player_analysis(self.context, {"riot_puuid": "1"})
        analyze.assert_called_once_with(puuid="1", match_id=None, routing_region="americas", champion="Yunara",
                                        opponent="Kaisa", kills=13, deaths=7, assists=11, specific_game_index=3)

    def test_invalid_selector_rejected_before_riot(self):
        """
        Explain an invalid index without clamping it or starting match retrieval.
        """
        self.context.player_analysis.specific_game_index = 0
        response = self.chat()
        self.assertIn("at least 1", response.answer)
        self.ids.assert_not_called()
        self.mocks["ask_gemini"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
