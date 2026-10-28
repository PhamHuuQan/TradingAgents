"""Agents on the schema-only structured-output path must not invite tool calls (#1130).

`with_structured_output` binds exactly one tool (the schema). A prompt that
primes tool use makes models emit an unknown `web_search` call, which discards
the structured attempt and forces a free-text retry — an extra LLM round trip
and the loss of typed output.

These assert the constraint reaches the *rendered* prompt each agent actually
sends, not merely that the constant is referenced in the module.
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

import tradingagents.agents.analysts.sentiment_analyst as sentiment
from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.structured import NO_EXTERNAL_TOOLS
from tradingagents.agents.trader.trader import create_trader


def _capturing_llm(captured: dict, result):
    """LLM whose structured binding records the prompt it was handed."""
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: (
        captured.__setitem__("prompt", prompt) or result
    )
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def _prompt_text(prompt) -> str:
    """Flatten a captured prompt (str, message list, or objects) to text."""
    if isinstance(prompt, str):
        return prompt
    parts = []
    for m in prompt:
        parts.append(m.get("content", "") if isinstance(m, dict) else getattr(m, "content", ""))
    return "\n".join(str(p) for p in parts)


@pytest.mark.unit
def test_trader_prompt_states_constraint():
    from tradingagents.agents.schemas import TraderAction, TraderProposal

    captured = {}
    llm = _capturing_llm(captured, TraderProposal(action=TraderAction.BUY, reasoning="x"))
    create_trader(llm)({
        "company_of_interest": "NVDA",
        "investment_plan": "**Recommendation**: Buy",
        "market_report": "Current price $189.5; ATR 4.2.",
    })
    prompt_text = _prompt_text(captured["prompt"])
    assert NO_EXTERNAL_TOOLS in prompt_text
    assert "PRICE-UNIT CONSISTENCY" in prompt_text
    assert "same full-VND scale" in prompt_text
    assert "do not invent a new entry or mandatory stop-loss" in prompt_text


@pytest.mark.unit
def test_research_manager_prompt_states_constraint():
    from tradingagents.agents.schemas import PortfolioRating, ResearchPlan

    captured = {}
    llm = _capturing_llm(
        captured,
        ResearchPlan(
            recommendation=PortfolioRating.BUY, rationale="x", strategic_actions="y"
        ),
    )
    create_research_manager(llm)({
        "company_of_interest": "NVDA",
        "investment_debate_state": {
            "history": "h", "bull_history": "b", "bear_history": "r",
            "current_response": "", "count": 1,
        },
    })
    assert NO_EXTERNAL_TOOLS in _prompt_text(captured["prompt"])


@pytest.mark.unit
def test_portfolio_manager_prompt_states_constraint():
    from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating

    captured = {}
    llm = _capturing_llm(
        captured,
        PortfolioDecision(
            rating=PortfolioRating.HOLD,
            executive_summary="x",
            investment_thesis="y",
        ),
    )
    risk = {
        "history": "h", "aggressive_history": "a", "conservative_history": "c",
        "neutral_history": "n", "current_aggressive_response": "",
        "current_conservative_response": "", "current_neutral_response": "",
        "latest_speaker": "Neutral", "count": 1,
    }
    create_portfolio_manager(llm)({
        "company_of_interest": "NVDA",
        "risk_debate_state": risk,
        "investment_plan": "plan",
        "trader_investment_plan": "trader plan",
    })
    assert NO_EXTERNAL_TOOLS in _prompt_text(captured["prompt"])


@pytest.mark.unit
def test_sentiment_prompt_states_constraint(monkeypatch):
    from tradingagents.agents.schemas import SentimentBand, SentimentReport

    # Pre-fetched sources are stubbed so the prompt builds without network I/O.
    monkeypatch.setattr(sentiment, "fetch_stocktwits_messages", lambda *a, **k: "st")
    monkeypatch.setattr(sentiment, "fetch_reddit_posts", lambda *a, **k: "rd")
    monkeypatch.setattr(sentiment.get_news, "func", lambda *a, **k: "news", raising=False)

    captured = {}
    llm = _capturing_llm(captured, SentimentReport(
        overall_band=SentimentBand.BULLISH, overall_score=7.5,
        confidence="high", narrative="n",
    ))
    sentiment.create_sentiment_analyst(llm)({
        "company_of_interest": "NVDA", "trade_date": "2026-01-15",
        "asset_type": "stock", "messages": [],
    })
    text = _prompt_text(captured["prompt"])
    assert NO_EXTERNAL_TOOLS in text
    # This agent binds no tools, so tool-range wording must not reappear.
    assert "tool-call date ranges" not in text


@pytest.mark.unit
def test_tool_using_analysts_keep_their_date_guidance():
    # The analysts that really do call tools keep the wording that anchors their
    # tool date ranges (#836) — this fix is scoped to no-tool agents.
    import tradingagents.agents.analysts.market_analyst as market
    import tradingagents.agents.analysts.news_analyst as news
    for module in (market, news):
        assert "tool-call date ranges" in inspect.getsource(module)


@pytest.mark.unit
def test_constraint_text_is_unambiguous():
    assert "do not call external tools" in NO_EXTERNAL_TOOLS.lower()
    # No template braces: it is embedded in ChatPromptTemplate strings, where
    # braces would be parsed as input variables.
    assert "{" not in NO_EXTERNAL_TOOLS and "}" not in NO_EXTERNAL_TOOLS


@pytest.mark.unit
def test_the_sentiment_prompt_names_the_subreddits_searched(monkeypatch):
    from tradingagents.agents.schemas import SentimentBand, SentimentReport

    monkeypatch.setattr(sentiment, "fetch_stocktwits_messages", lambda *a, **k: "st")
    monkeypatch.setattr(sentiment, "fetch_reddit_posts", lambda *a, **k: "rd")
    monkeypatch.setattr(sentiment.get_news, "func", lambda *a, **k: "news", raising=False)
    captured = {}
    llm = _capturing_llm(captured, SentimentReport(
        overall_band=SentimentBand.NEUTRAL, overall_score=5.0, confidence="low", narrative="n",
    ))
    sentiment.create_sentiment_analyst(llm)({
        "company_of_interest": "BTC-USD", "trade_date": "2026-01-15",
        "asset_type": "crypto", "messages": [],
    })
    text = _prompt_text(captured["prompt"])
    assert "r/Bitcoin, r/CryptoCurrency, r/CryptoMarkets" in text
    assert "wallstreetbets" not in text



@pytest.mark.unit
def test_risk_debaters_receive_social_coverage_guardrail():
    from copy import deepcopy
    from tradingagents.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
    from tradingagents.agents.risk_mgmt.conservative_debator import create_conservative_debator
    from tradingagents.agents.risk_mgmt.neutral_debator import create_neutral_debator

    source_limited_state = {
        "company_of_interest": "FPT",
        "asset_type": "stock",
        "market_report": "FPT market report",
        "sentiment_report": (
            "StockTwits provider unavailable due to HTTPError. "
            "Reddit returned no matching posts in the requested window; "
            "this is not proof of zero discussion everywhere."
        ),
        "news_report": "News report not available.",
        "fundamentals_report": "DATA_UNAVAILABLE: balance sheet and cash flow.",
        "trader_investment_plan": "Action: Hold",
        "risk_debate_state": {
            "history": "",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "count": 0,
        },
    }

    for factory in (
        create_aggressive_debator,
        create_conservative_debator,
        create_neutral_debator,
    ):
        llm = MagicMock()
        llm.invoke.return_value.content = "Risk argument."
        factory(llm)(deepcopy(source_limited_state))
        prompt = llm.invoke.call_args.args[0]
        assert "SOCIAL COVERAGE LIMITATION" in prompt
        assert "Do not infer low retail interest" in prompt
        assert "smart-money accumulation/distribution" in prompt



@pytest.mark.unit
def test_hold_trader_clears_stop_loss_without_explicit_portfolio_context():
    from tradingagents.agents.schemas import TraderAction, TraderProposal

    captured = {}
    llm = _capturing_llm(
        captured,
        TraderProposal(
            action=TraderAction.HOLD,
            reasoning="Maintain the current position and wait.",
            stop_loss=52000.0,
            position_sizing="Maintain current position",
        ),
    )
    output = create_trader(llm)({
        "company_of_interest": "FPT",
        "investment_plan": "Recommendation: Hold",
        "market_report": "FPT close 55,400 VND; support 54,075 VND.",
    })["trader_investment_plan"]

    assert "**Action**: Hold" in output
    assert "**Stop Loss**: not provided" in output
    assert "52000.0" not in output


@pytest.mark.unit
def test_portfolio_manager_discloses_missing_personal_portfolio_context():
    from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating

    captured = {}
    llm = _capturing_llm(
        captured,
        PortfolioDecision(
            rating=PortfolioRating.HOLD,
            executive_summary="Set a stop-loss at 52,000.",
            investment_thesis="The price trend is weak.",
        ),
    )
    risk = {
        "history": "Risk debate",
        "aggressive_history": "Aggressive",
        "conservative_history": "Conservative",
        "neutral_history": "Neutral",
        "current_aggressive_response": "",
        "current_conservative_response": "",
        "current_neutral_response": "",
        "latest_speaker": "Neutral",
        "count": 1,
    }
    output = create_portfolio_manager(llm)({
        "company_of_interest": "FPT",
        "risk_debate_state": risk,
        "investment_plan": "Recommendation: Hold",
        "trader_investment_plan": "Action: Hold",
    })["final_trade_decision"]

    assert "Portfolio Context Limitation" in output
    assert "not a personalized mandatory stop-loss or order instruction" in output
    assert "\n\n**Portfolio Context Limitation**" in output
