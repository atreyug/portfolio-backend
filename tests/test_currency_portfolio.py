import unittest

from pydantic import ValidationError

from schema.portfolio import StockAnalysisRequest
from utils.portfolio_calculator import calculate_stock_portfolio


def holding(symbol="RELIANCE", currency=None, exchange=None, buy_price=100):
    value = {
        "client_id": "client-1",
        "symbol": symbol,
        "quantity": 10,
        "buy_price": buy_price,
    }
    if currency is not None:
        value["currency"] = currency
    if exchange is not None:
        value["exchange"] = exchange
    return value


class CurrencyPortfolioTests(unittest.TestCase):

  def test_inr_portfolio_uses_market_price_and_inr_totals(self):
    result = calculate_stock_portfolio(
        [holding(currency="INR")],
        {"RELIANCE": {"price": 120, "currency": "INR", "exchange": "NSE"}},
        "INR",
        {("INR", "INR"): 1.0},
    )
    position = result["positions"][0]
    self.assertEqual(position["current_value"], 1200)
    self.assertEqual(position["profit_loss"], 200)
    self.assertEqual(position["formatted_current_value"], chr(0x20B9) + "1,200.00")


  def test_usd_portfolio_uses_usd_market_price(self):
    result = calculate_stock_portfolio(
        [holding("AAPL", "USD", buy_price=120)],
        {"AAPL": {"price": 120, "currency": "USD", "exchange": "NASDAQ"}},
        "USD",
        {("USD", "USD"): 1.0},
    )
    self.assertEqual(result["reporting_currency"], "USD")
    self.assertEqual(result["positions"][0]["formatted_current_value"], "$1,200.00")


  def test_same_currency_aapl_does_not_require_fx_rate(self):
    result = calculate_stock_portfolio(
        [holding("AAPL", "USD", buy_price=120)],
        {"AAPL": {"price": 134.656, "currency": "USD", "exchange": "NASDAQ"}},
        "USD",
        {},
    )
    position = result["positions"][0]
    self.assertEqual(position["invested"], 1200)
    self.assertEqual(position["invested_value"], 1200)
    self.assertEqual(position["formatted_invested"], "$1,200.00")
    self.assertEqual(position["current_value"], 1346.56)
    self.assertEqual(position["profit_loss"], 146.56)
    self.assertAlmostEqual(position["profit_loss_percentage"], 12.2133)


  def test_usd_without_reporting_currency_keeps_totals_unavailable(self):
    result = calculate_stock_portfolio(
        [holding("AAPL", "USD", buy_price=120)],
        {"AAPL": {"price": 134.656, "currency": "USD"}},
        None,
        {},
    )
    self.assertIsNone(result["total_invested"])
    self.assertIsNone(result["current_value"])


  def test_missing_currency_can_be_inferred_from_known_exchange(self):
    result = calculate_stock_portfolio(
        [holding(exchange="NSE")],
        {"RELIANCE": {"price": 120, "currency": "INR", "exchange": "NSE"}},
        "INR",
        {("INR", "INR"): 1.0},
    )
    self.assertEqual(result["positions"][0]["purchase_currency"], "INR")


  def test_mixed_currency_portfolio_converts_to_reporting_currency(self):
    result = calculate_stock_portfolio(
        [holding(currency="INR"), holding("AAPL", "USD")],
        {
            "RELIANCE": {"price": 120, "currency": "INR"},
            "AAPL": {"price": 120, "currency": "USD"},
        },
        "INR",
        {("INR", "INR"): 1.0, ("USD", "INR"): 83.0},
    )
    self.assertEqual(result["total_invested"], 84000)
    self.assertEqual(result["current_value"], 100800)
    self.assertAlmostEqual(sum(position["weight"] for position in result["positions"]), 100)


  def test_unavailable_market_price_does_not_use_buy_price(self):
    result = calculate_stock_portfolio(
        [holding(currency="INR")],
        {"RELIANCE": {"price": None, "currency": "INR"}},
        "INR",
        {("INR", "INR"): 1.0},
    )
    position = result["positions"][0]
    self.assertIsNone(position["current_price"])
    self.assertIsNone(position["current_value"])
    self.assertIsNone(position["profit_loss"])
    self.assertIsNone(result["current_value"])


  def test_unknown_currency_is_warning_not_guess(self):
    result = calculate_stock_portfolio(
        [holding()],
        {"RELIANCE": {"price": 120, "currency": "INR"}},
        None,
        {},
    )
    self.assertIsNone(result["positions"][0]["purchase_currency"])
    self.assertTrue(any("purchase currency" in warning for warning in result["warnings"]))


  def test_schema_rejects_unsupported_currency(self):
    with self.assertRaises(ValidationError):
        StockAnalysisRequest(holdings=[{**holding(), "currency": "EUR"}])


if __name__ == "__main__":
    unittest.main()
