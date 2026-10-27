"""Polymarket prediction-market vendor: forward-looking filtering, volume
ranking, formatting, graceful degradation, and router integration.

All API access is mocked, so these run without a network connection.
"""
import copy
import unittest
from unittest import mock

import pytest
import requests

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import router
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.vendors import polymarket
from tradingagents.agents.tools import get_prediction_markets


def _market(question, prob, *, volume, end_date, closed=False, wk=None):
    return {
        "question": question,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": f'["{prob}", "{round(1 - prob, 4)}"]',
        "volumeNum": volume,
        "endDate": end_date,
        "closed": closed,
        "oneWeekPriceChange": wk,
    }


# One event with a mix: a high-volume open market, a closed one, a past-dated
# one, and a lower-volume open one. Far-future / far-past dates keep the test
# independent of the real clock.
_SEARCH = {
    "events": [
        {
            "markets": [
                _market("Open big?", 0.76, volume=5_000_000, end_date="2030-12-31T00:00:00Z", wk=-0.045),
                _market("Resolved already?", 1.0, volume=9_000_000, end_date="2030-12-31T00:00:00Z", closed=True),
                _market("Past event?", 0.5, volume=8_000_000, end_date="2020-01-01T00:00:00Z"),
                _market("Open small?", 0.30, volume=1_000, end_date="2030-06-30T00:00:00Z"),
            ]
        }
    ]
}


@pytest.mark.unit
class PolymarketFilterTests(unittest.TestCase):
    def test_irrelevant_high_volume_sports_market_is_filtered_out(self):
        data = {
            "events": [
                {
                    "title": "Fed policy",
                    "slug": "fed-policy-outlook-2026",
                    "markets": [
                        _market(
                            "How many Fed rate cuts in 2026?",
                            0.72,
                            volume=100_000,
                            end_date="2030-12-31T00:00:00Z",
                        )
                    ],
                },
                {
                    "title": "AFC Asian Cup 2026",
                    "slug": "afc-asian-cup-2026-winner",
                    "markets": [
                        _market(
                            "AFC Asian Cup 2026 winner?",
                            0.50,
                            volume=50_000_000,
                            end_date="2027-12-31T00:00:00Z",
                        )
                    ],
                },
            ]
        }
        with mock.patch.object(polymarket, "_request", return_value=data):
            out = polymarket.get_prediction_markets("Fed rate cut 2026", limit=10)

        self.assertIn("How many Fed rate cuts in 2026?", out)
        self.assertNotIn("AFC Asian Cup", out)
        self.assertNotIn("$50,000,000 volume", out)



    def test_closed_and_past_markets_are_excluded(self):
        with mock.patch.object(polymarket, "_request", return_value=_SEARCH):
            out = polymarket.get_prediction_markets("open", limit=10)
        self.assertIn("Open big?", out)
        self.assertIn("Open small?", out)
        self.assertNotIn("Resolved already?", out)  # closed
        self.assertNotIn("Past event?", out)         # endDate in the past

    def test_ranked_by_volume(self):
        with mock.patch.object(polymarket, "_request", return_value=_SEARCH):
            out = polymarket.get_prediction_markets("open", limit=10)
        self.assertLess(out.index("Open big?"), out.index("Open small?"))

    def test_limit_caps_results(self):
        with mock.patch.object(polymarket, "_request", return_value=_SEARCH):
            out = polymarket.get_prediction_markets("open", limit=1)
        self.assertIn("Open big?", out)
        self.assertNotIn("Open small?", out)


@pytest.mark.unit
class PolymarketFormatTests(unittest.TestCase):
    def test_probability_volume_and_weekly_change_render(self):
        with mock.patch.object(polymarket, "_request", return_value=_SEARCH):
            out = polymarket.get_prediction_markets("open", limit=10)
        self.assertIn("Yes 76%", out)
        self.assertIn("$5,000,000 volume", out)
        self.assertIn("resolves 2030-12-31", out)
        self.assertIn("1-week -4.5pp", out)  # -0.045 -> -4.5pp

    def test_market_source_url_and_observation_timestamp_are_rendered(self):
        data = copy.deepcopy(_SEARCH)
        data["events"][0]["slug"] = "fed-rate-cut-2026"
        with mock.patch.object(polymarket, "_request", return_value=data):
            out = polymarket.get_prediction_markets("Fed rate cut", limit=10)
        self.assertIn("Retrieved at (UTC):", out)
        self.assertIn("Market URL: https://polymarket.com/event/fed-rate-cut-2026", out)
        self.assertIn("- API endpoint: https://gamma-api.polymarket.com/public-search", out)

    def test_missing_provider_market_slug_is_not_replaced_with_a_guessed_url(self):
        with mock.patch.object(polymarket, "_request", return_value=_SEARCH):
            out = polymarket.get_prediction_markets("open", limit=10)
        self.assertIn("Market URL: unavailable from the provider", out)
        self.assertNotIn("https://polymarket.com/event/", out)

    def test_weekly_change_omitted_when_absent(self):
        # "Open small?" has wk=None -> no 1-week clause on its line.
        with mock.patch.object(polymarket, "_request", return_value=_SEARCH):
            out = polymarket.get_prediction_markets("open", limit=10)
        small_line = next(ln for ln in out.splitlines() if "Open small?" in ln)
        self.assertNotIn("1-week", small_line)

    def test_no_matches_reports_clearly(self):
        with mock.patch.object(polymarket, "_request", return_value={"events": []}):
            out = polymarket.get_prediction_markets("obscure ticker", limit=6)
        self.assertIn("No open prediction markets", out)


@pytest.mark.unit
class PolymarketResilienceTests(unittest.TestCase):
    def test_network_error_degrades_gracefully(self):
        # An external-service hiccup must not raise into the analyst.
        with mock.patch.object(
            polymarket, "_request", side_effect=requests.RequestException("boom")
        ):
            out = polymarket.get_prediction_markets("Fed rate cut")
        self.assertIn("unavailable", out.lower())
        self.assertIn("Fed rate cut", out)


@pytest.mark.unit
class PolymarketRoutingTests(unittest.TestCase):
    def setUp(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    def tearDown(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    def test_category_routes_to_polymarket(self):
        self.assertEqual(
            router.get_category_for_method("get_prediction_markets"),
            "prediction_markets",
        )
        set_config({"data_vendors": {"prediction_markets": "polymarket"}})
        with mock.patch.dict(
            router.VENDOR_METHODS,
            {"get_prediction_markets": {"polymarket": lambda *a, **k: "POLY_OK"}},
            clear=False,
        ):
            out = router.route_to_vendor("get_prediction_markets", "fed", 5)
        self.assertEqual(out, "POLY_OK")


if __name__ == "__main__":
    unittest.main()



def test_tool_filters_unrelated_sports_topics_for_equity_before_provider_query():
    with mock.patch("tradingagents.agents.tools.route_to_vendor") as route:
        out = get_prediction_markets.func(
            "AFC Asian Cup 2027 Group E winner",
            6,
            "FPT",
            "stock",
            "2026-10-27",
        )

    assert "filtered" in out.lower()
    assert "no external market query was sent" in out.lower()
    route.assert_not_called()


def test_tool_still_queries_financially_relevant_prediction_markets():
    with mock.patch(
        "tradingagents.agents.tools.route_to_vendor",
        return_value="POLYMARKET_RESULT",
    ) as route:
        out = get_prediction_markets.func(
            "Fed rate cut 2026",
            6,
            "FPT",
            "stock",
            "2026-10-27",
        )

    assert out == "POLYMARKET_RESULT"
    route.assert_called_once_with("get_prediction_markets", "Fed rate cut 2026", 6, "2026-10-27")
