"""Polymarket prediction-market vendor.

Surfaces live, market-implied probabilities for forward-looking events (Fed
decisions, recession, elections, geopolitics, crypto) to the news analyst, as a
complement to news (what happened) and FRED macro data (where things stand):
what the crowd actually prices to happen next.

Uses Polymarket's public Gamma API (https://gamma-api.polymarket.com) — no key,
no auth. Each market's ``outcomePrices`` are the implied probabilities of its
outcomes (a "Yes" at 0.76 means the market prices a 76% chance).
"""
import json
import logging
import re
from datetime import UTC, datetime
from urllib.parse import quote, urlparse

import requests

from tradingagents.dataflows.date_window import is_historical

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"

# Network timeout (seconds), consistent with the other vendors.
REQUEST_TIMEOUT = 30

# Default number of markets to return, ranked by traded volume.
DEFAULT_LIMIT = 6


def _request(path: str, params: dict) -> dict:
    response = requests.get(
        f"{GAMMA_BASE}/{path}", params=params, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def _parse_json_list(value) -> list:
    """Gamma encodes ``outcomes``/``outcomePrices`` as JSON-string arrays."""
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def _is_forward_looking(market: dict, now: datetime) -> bool:
    """Keep only open markets that resolve in the future.

    ``closed`` is the reliable resolved flag (``active`` stays True even for
    settled markets), and a past ``endDate`` means the event already resolved —
    either way it is not a forward-looking signal.
    """
    if market.get("closed"):
        return False
    end_date = market.get("endDate")
    if end_date:
        try:
            if datetime.fromisoformat(end_date.replace("Z", "+00:00")) < now:
                return False
        except ValueError:
            pass
    return bool(_parse_json_list(market.get("outcomePrices"))) and bool(
        _parse_json_list(market.get("outcomes"))
    )



def _market_url(event: dict, market: dict) -> str:
    """Return a traceable official market URL only when supported by provider fields."""
    direct = market.get("url") or event.get("url")
    if isinstance(direct, str) and direct.strip():
        parsed = urlparse(direct.strip())
        if parsed.scheme == "https" and parsed.hostname in {"polymarket.com", "www.polymarket.com"}:
            return direct.strip()
    slug = event.get("slug") or market.get("slug")
    if isinstance(slug, str) and slug.strip():
        return f"https://polymarket.com/event/{quote(slug.strip(), safe='-')}"
    return ""

_TOPIC_STOPWORDS = {
    "a", "an", "and", "are", "be", "by", "can", "did", "does", "for",
    "from", "how", "in", "is", "it", "of", "on", "or", "the", "to",
    "was", "were", "what", "when", "where", "which", "who", "why",
    "will", "would", "market", "markets", "prediction", "probability",
}


def _topic_tokens(topic: str) -> set[str]:
    """Extract content tokens for a conservative local relevance check."""
    return {
        token for token in re.findall(r"[a-z0-9]+", (topic or "").casefold())
        if len(token) > 1 and token not in _TOPIC_STOPWORDS
    }


def _is_topic_relevant(topic: str, event: dict, market: dict) -> bool:
    """Drop broad-search results whose event/question/slug shares no topic token."""
    terms = _topic_tokens(topic)
    if not terms:
        return False
    searchable_text = " ".join(
        str(value or "")
        for value in (
            event.get("title"),
            event.get("slug"),
            event.get("description"),
            market.get("question"),
            market.get("slug"),
        )
    ).casefold()
    market_terms = set(re.findall(r"[a-z0-9]+", searchable_text))
    return bool(terms & market_terms)


def get_prediction_markets(topic: str, limit: int | None = None, as_of_date: str | None = None) -> str:
    """Return live prediction-market probabilities for an event topic.

    Args:
        topic: Event keyword(s), e.g. "Fed rate cut", "recession 2026",
            "US election", or a sector/company event.
        limit: Max markets to return (ranked by traded volume); ``None`` uses
            DEFAULT_LIMIT.
        as_of_date: The analysis date. Polymarket serves only live odds, so a
            date before today withholds them.

    Returns:
        A markdown report of the most-traded open markets matching the topic,
        each with its implied probability, traded volume, resolution date, and
        recent (1-week) move.
    """
    if is_historical(as_of_date):
        return (
            f"Prediction-market odds are withheld for {as_of_date}. Polymarket serves "
            f"only live odds on open markets, with no historical vintage, so serving "
            f"them would put post-decision information into a {as_of_date} analysis."
        )
    if limit is None:
        limit = DEFAULT_LIMIT

    try:
        data = _request("public-search", {"q": topic, "limit_per_type": 20})
    except requests.RequestException as e:
        logger.warning("Polymarket search failed for %r: %s", topic, e)
        return (
            f"Polymarket data is currently unavailable (network error: {e}). "
            f"Proceed without prediction-market signal for '{topic}'."
        )

    now = datetime.now(UTC)
    retrieved_at = now.isoformat()
    candidates = [
        (event, market)
        for event in data.get("events", [])
        for market in event.get("markets", [])
        if _is_forward_looking(market, now)
        and _is_topic_relevant(topic, event, market)
    ]
    candidates.sort(key=lambda pair: pair[1].get("volumeNum") or 0, reverse=True)

    header = (
        f'## Polymarket prediction markets: "{topic}"\n'
        f"- Source: Polymarket public Gamma API\n"
        f"- API endpoint: {GAMMA_BASE}/public-search\n"
        f"- Retrieved at (UTC): {retrieved_at}\n"
        f"Live, market-implied probabilities (higher traded volume = deeper, "
        f"more reliable). A probability is the crowd's priced odds of the event, "
        f"not a forecast you should take as certain.\n\n"
    )

    if not candidates:
        return header + (
            f"No open, topic-relevant prediction markets matched '{topic}'. Polymarket coverage "
            f"is concentrated in macro, political, geopolitical, and crypto "
            f"events; a specific equity may have none."
        )

    lines = []
    for event, m in candidates[:limit]:
        prices = _parse_json_list(m.get("outcomePrices"))
        outcomes = _parse_json_list(m.get("outcomes"))
        try:
            prob = float(prices[0])
        except (ValueError, IndexError):
            continue
        label = outcomes[0] if outcomes else "Yes"
        volume = m.get("volumeNum") or 0
        end_date = (m.get("endDate") or "")[:10]
        wk = m.get("oneWeekPriceChange")
        wk_str = (
            f", 1-week {wk * 100:+.1f}pp"
            if isinstance(wk, (int, float)) and wk
            else ""
        )
        market_url = _market_url(event, m)
        lines.append(
            f"- **{m.get('question')}** — {label} {prob:.0%} "
            f"(${volume:,.0f} volume, resolves {end_date}{wk_str})\n"
            f"  - Observed at (UTC): {retrieved_at}\n"
            + (
                f"  - Market URL: {market_url}"
                if market_url
                else "  - Market URL: unavailable from the provider; do not treat this item as directly source-linked"
            )
        )

    return header + "\n".join(lines) + "\n"
