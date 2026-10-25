"""
AI context builders.

Each function returns a plain string prompt that is passed verbatim to
the LLM.  All numeric values in the prompts come from deterministic
backend calculations — the LLM must not re-derive or contradict them.
"""

import json
from typing import Any


def _question_section(question: str | None) -> str:
    if not question:
        return ""
    return f"""

USER QUESTION
{question}

Answer the user's question using only the data supplied in this prompt.
If the required data is unavailable, state that clearly and explain why.
Do not invent figures or make unverifiable claims to answer the question.
"""


def build_portfolio_context(
    client_id: str,
    portfolio_metrics: dict,
    market_data: dict,
    news_data: dict,
    requested_symbol: str,
    analysis_question: str | None = None,
) -> str:

    requested_symbol = requested_symbol.strip().upper()

    return f"""
STOCK PORTFOLIO ANALYSIS

Client ID:
{client_id}

PRIMARY STOCK:
{requested_symbol}


CALCULATED PORTFOLIO POSITIONS

{json.dumps(portfolio_metrics, indent=2, default=str)}


LIVE MARKET DATA USED FOR CALCULATIONS

{json.dumps(market_data, indent=2, default=str)}


FINANCIAL NEWS

{json.dumps(news_data, indent=2, default=str)}


ANALYSIS INSTRUCTIONS

Analyze the supplied portfolio positions. The calculated values above
are authoritative for the JSON response: use the API-returned market
price for current value, gain/loss, percentage return, and weight.
If a market price is null, treat all market-dependent values for that
position as unavailable; never substitute the buy price.

Use the supplied purchase_currency, market_currency, reporting_currency,
exchange rates, and formatted monetary values exactly as provided. Do not
recalculate, round differently, convert, or invent any structured metric.
If a structured metric is null, say that it is unavailable and explain the
corresponding warning when present.

One quote is a point-in-time observation. Do not call the stock stable,
stagnant, volatile, or low-interest based on one quote. If news is empty,
do not infer investor interest, price movement, or future volatility.
Use ₹ for INR and $ for USD when referring to amounts.

The primary stock for detailed discussion is {requested_symbol}, while
portfolio totals and weights must reflect all supplied holdings.

Explain:

1. Current position in {requested_symbol}
2. Current market price and only verified market conditions supplied
3. Gain/loss and return, if available
4. Portfolio exposure to {requested_symbol}
5. Relevant financial news
6. Potential impact of the news on {requested_symbol}
7. Key risks and uncertainties

Do not introduce numeric values that are not present in the calculated
portfolio or market data blocks. Describe general risks as possibilities,
not as observed facts about this stock.

Do not invent financial information.

Do not use information from other stocks
as evidence for this analysis.

Clearly distinguish facts from interpretation.

Do not make guaranteed predictions.

Do not provide a guaranteed buy or sell recommendation.
{_question_section(analysis_question)}"""


def build_mf_context(
    client_id: str,
    portfolio_metrics: dict[str, Any],
    nav_data: dict[str, Any],
    news_data: dict[str, Any] | None = None,
    analysis_question: str | None = None,
) -> str:
    """Build LLM prompt for mutual fund holding analysis."""

    news_section = ""
    if news_data:
        news_section = f"""

FINANCIAL NEWS

{json.dumps(news_data, indent=2, default=str)}
"""

    return f"""
MUTUAL FUND PORTFOLIO ANALYSIS

Client ID:
{client_id}


CALCULATED PORTFOLIO METRICS

{json.dumps(portfolio_metrics, indent=2, default=str)}


LIVE NAV DATA FROM MFNAV.IN

{json.dumps(nav_data, indent=2, default=str)}
{news_section}

ANALYSIS INSTRUCTIONS

Analyze the supplied mutual fund holdings using only the data provided above.

Key rules:
1. NAV values shown are from mfnav.in. Note the nav_date and nav_source for
   each scheme — a stale NAV date means the value may not be live.
2. Do not invent gain/loss, returns, or valuations not present in the data.
3. If a holding shows current_value: null, state that the valuation is
   unavailable and explain the likely cause (missing NAV or units).
4. Do not treat a null monthly_sip_amount as zero — it means unknown.
5. Use ₹ for INR amounts.
6. Do not guarantee future returns or recommend specific schemes to buy/sell.
7. Clearly distinguish between values supplied by the client statement and
   values recalculated using live NAV data.

Explain:
1. Portfolio total valuation and data quality (live vs stale NAVs)
2. Scheme-wise performance — current value, gain/loss, and return for each
3. Portfolio concentration by fund house and category where available
4. Key risks: concentration, stale NAVs, missing data
5. Overall return assessment based on available data

Clearly distinguish facts from interpretation. Do not guarantee returns.
{_question_section(analysis_question)}"""


def build_projection_context(
    projection_type: str,
    inputs: dict[str, Any],
    result: dict[str, Any],
    analysis_question: str | None = None,
) -> str:
    """Build LLM prompt for SIP / projection analysis."""

    return f"""
MUTUAL FUND SIP PROJECTION ANALYSIS

Projection type: {projection_type}


INPUTS PROVIDED

{json.dumps(inputs, indent=2, default=str)}


CALCULATED PROJECTION RESULT

{json.dumps(result, indent=2, default=str)}


ANALYSIS INSTRUCTIONS

Explain the projection results to the investor.

Key rules:
1. All numeric results above come from deterministic calculations. Do not
   recalculate, contradict, or alter them.
2. The assumed_return_pct is an illustrative rate only. Markets are
   uncertain — never guarantee this return will be achieved.
3. If monthly_sip_amount was provided, the projection already accounts for
   both the existing corpus growth and the ongoing SIP contributions.
4. Do not double-count the monthly SIP.
5. If target_amount is present, explain the surplus or shortfall.
6. If additional_monthly_sip_required is present, explain what it means in
   plain language — it is the extra SIP needed beyond existing contributions.
7. Use ₹ for INR amounts. Do not invent currency symbols.
8. Use clear, plain language suitable for an individual investor.

Explain:
1. What the projection shows in plain terms
2. The key inputs and their significance
3. The projected outcome and what drives it (corpus growth vs SIP growth)
4. If a goal target is present: whether it will be met and by how much
5. Realistic caveats about return assumptions and market uncertainty

Do not recommend specific funds. Do not guarantee returns.
{_question_section(analysis_question)}"""
