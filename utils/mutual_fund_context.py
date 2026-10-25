from __future__ import annotations
from utils.ai_context import _question_section
import json


def _slim_portfolio(portfolio: dict, has_selected: bool) -> dict:
    """
    Keep the prompt small and avoid misleading numbers.

    Single-scheme analysis: the "portfolio" is just the selected scheme
    (weight = 100% by construction), so we do not send it at all.
    Full-portfolio analysis: send everything except the duplicated
    top_holdings list.
    """
    if has_selected:
        return {
            "note": (
                "Not provided for a single-scheme analysis. "
                "SELECTED HOLDING contains all the data for this scheme."
            )
        }

    return {k: v for k, v in portfolio.items() if k != "top_holdings"}


_SELECTED_ANALYSIS = """
For the selected scheme, analyze:

- Scheme name, fund house, category, sub-category, plan, option
- Number of folios and total units
- Current NAV (live) and current value
- Gross invested amount and cost basis
- Gain/loss and absolute return (live NAV)
- Folio-level XIRRs where supplied (statement date, see rule 16)
- 1M / 3M / 6M / 1Y NAV returns where available
- 3Y / 5Y CAGR where available
""".strip()


_PORTFOLIO_ANALYSIS = """
For the full portfolio, analyze:

- Total portfolio value, total invested amount, total cost basis
- Total gain/loss and total absolute return
- Number of schemes and number of folios
- Largest scheme and its weight
- AMC exposure and category exposure
- Concentration and diversification
- Unresolved schemes
""".strip()


_SELECTED_RESPONSE = """
Use these sections:

1. Fund Snapshot

2. Performance Analysis

3. Allocation & Concentration
   Write exactly one line: "Not available in a single-scheme analysis."

4. Risk Observations

5. Data Gaps

6. What to Monitor

Keep calculations factual and distinguish them clearly from interpretation.
""".strip()


_PORTFOLIO_RESPONSE = """
Use these sections:

1. Portfolio Snapshot

2. Performance Analysis

3. Allocation & Concentration

4. Risk Observations

5. Data Gaps

6. What to Monitor

Keep calculations factual and distinguish them clearly from interpretation.
""".strip()


def build_mutual_fund_context(
    client_id: str,
    portfolio_metrics: dict,
    selected_holding: dict | None = None,
    nav_performance: dict | None = None,
    fund_details: dict | None = None,
    analysis_question: str | None = None,
) -> str:
    """
    Build grounded context for mutual-fund analysis.
    """

    has_selected = bool(selected_holding)

    selected_text = json.dumps(
        selected_holding or {},
        indent=2,
        default=str,
    )

    performance_text = json.dumps(
        nav_performance or {},
        indent=2,
        default=str,
    )

    details_text = json.dumps(
        {k: v for k, v in (fund_details or {}).items() if v is not None},
        indent=2,
        default=str,
    )

    portfolio_text = json.dumps(
        _slim_portfolio(portfolio_metrics, has_selected),
        indent=2,
        default=str,
    )

    if has_selected:
        scope = (
            "Analyze the selected mutual-fund scheme "
            "and its folios. This is a SINGLE-SCHEME analysis."
        )
        analysis_block = _SELECTED_ANALYSIS
        response_block = _SELECTED_RESPONSE
    else:
        scope = "Analyze the client's complete mutual-fund portfolio."
        analysis_block = _PORTFOLIO_ANALYSIS
        response_block = _PORTFOLIO_RESPONSE

    return f"""
MUTUAL FUND PORTFOLIO ANALYSIS

CLIENT ID
{client_id}

SCOPE
{scope}


IMPORTANT DATA MODEL

The supplied mutual-fund payload is folio-level.

A single mutual-fund scheme can have multiple folios.

Example:

Scheme A
    ├── Folio 1
    ├── Folio 2
    └── Folio 3

The system aggregates those folios into one scheme-level holding
for exposure and portfolio analysis while preserving the original
folio-level details.


SELECTED HOLDING

{selected_text}


NAV PERFORMANCE

{performance_text}


FUND DETAILS

{details_text}


PORTFOLIO METRICS

{portfolio_text}


RULES

1. Use ONLY the supplied data.

2. Do not invent:
   - AUM
   - expense ratio
   - benchmark
   - rating
   - underlying holdings
   - alpha
   - beta
   - Sharpe ratio
   - volatility
   - future returns
   - any unavailable metric

3. If a metric is unavailable, explicitly say:
   "Not available in the supplied data."

4. Treat the latest NAV returned by mfnav as the current NAV.

5. Distinguish:
   - NAV performance
   - actual client holding performance

6. A scheme-level holding may contain multiple folios.

7. Do not treat multiple folios of the same scheme as multiple
   independent mutual funds.

8. Gross invested amount is based on:
   Purchase + Switch In + Dividend Reinvestment.

9. Cost basis is:
   Gross invested amount - Redemption - Switch Out.

10. Do not create a scheme-level XIRR by averaging folio XIRRs.

11. Do not guarantee future returns.

12. Do not provide an unconditional buy/sell recommendation.

13. Clearly mention unresolved schemes and missing data.

14. Every field ending in "_pct" is ALREADY a percentage value.
    0.4737 means 0.4737%, NOT 47.37%. Never multiply by 100.
    Write such values with a % sign exactly as supplied.

15. If SCOPE is a single-scheme analysis, PORTFOLIO METRICS are not
    provided. Do not state or imply anything about the client's overall
    portfolio, weights, concentration, diversification, AMC exposure or
    category exposure.

16. Folio XIRR values come from the supplied request and are as of the
    statement date and statement NAV. They are NOT recomputed at the live
    NAV. Absolute return and gain/loss use the live NAV. If
    statement_nav / statement_value are present, they are the statement's
    own figures. Never infer underperformance from XIRR when the live
    gain/loss is positive; explain that the figures are as of different
    dates instead.


ANALYSIS

{analysis_block}


FINAL RESPONSE

{response_block}
{_question_section(analysis_question)}
""".strip()