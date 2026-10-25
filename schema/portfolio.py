from __future__ import annotations

from datetime import date
from enum import Enum
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProjectionType(str, Enum):
    FUTURE_VALUE = "FUTURE_VALUE"
    REQUIRED_SIP = "REQUIRED_SIP"
    TIME_TO_TARGET = "TIME_TO_TARGET"
    LUMPSUM_GROWTH = "LUMPSUM_GROWTH"


class CurrencyCode(str, Enum):
    INR = "INR"
    USD = "USD"


# ---------------------------------------------------------------------------
# Stock analysis
# ---------------------------------------------------------------------------

class StockHoldingRequest(BaseModel):
    client_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    quantity: float = Field(gt=0)
    buy_price: float = Field(gt=0)
    security_name: str | None = None
    isin: str | None = None
    exchange: str | None = None
    buy_date: date | None = None
    current_price: float | None = Field(default=None, gt=0)
    currency: CurrencyCode | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class StockAnalysisRequest(BaseModel):
    holdings: list[StockHoldingRequest] = Field(min_length=1)
    reporting_currency: CurrencyCode | None = None
    analysis_question: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def same_client(self):
        if len({holding.client_id for holding in self.holdings}) != 1:
            raise ValueError("All holdings must belong to the same client_id")
        return self

    @field_validator("analysis_question", mode="before")
    @classmethod
    def clean_question(cls, value):
        if value is None:
            return None
        value = str(value).strip()
        return value or None

# ---------------------------------------------------------------------------
# Mutual-fund holdings and optional transaction-level SIP data
# ---------------------------------------------------------------------------

class MutualFundHoldingRequest(BaseModel):
    client_id: str = Field(min_length=1)
    scheme_name: str = Field(min_length=1)
    units: float = Field(gt=0)
    scheme_code: str | None = None
    folio_no: str | None = None
    invested_value: float | None = Field(default=None, ge=0)
    current_nav: float | None = Field(default=None, gt=0)
    current_value: float | None = Field(default=None, ge=0)
    investment_date: date | None = None
    xirr_pct: float | None = None
    monthly_sip_amount: float | None = Field(
        default=None,
        ge=0,
        description="Known ongoing monthly SIP. None means unknown; use 0 only when confirmed no SIP is running.",
    )
    expected_return_pct: float | None = Field(
        default=None,
        gt=-100,
        description="Optional illustrative annual return assumption for this scheme; overrides goal-level base assumption.",
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class MutualFundTransactionRequest(BaseModel):
    """Transaction input used only for in-memory SIP/XIRR calculations."""

    scheme_code: str | None = None
    scheme_name: str | None = None
    transaction_date: date
    transaction_type: str = Field(min_length=1)
    amount: float | None = Field(default=None, ge=0)
    nav: float | None = Field(default=None, gt=0)
    units: float | None = Field(default=None, ge=0)

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def scheme_identifier_required(self):
        if not (self.scheme_code or self.scheme_name):
            raise ValueError("Each transaction requires scheme_code or scheme_name")
        return self


class MutualFundGoalRequest(BaseModel):
    """Goal projection across the customer's current mutual-fund schemes."""

    target_amount: float = Field(gt=0)
    duration_months: int | None = Field(default=None, gt=0)
    target_date: date | None = None
    expected_return_pct: float = Field(
        gt=-100,
        description="Required illustrative annual return assumption used when a scheme-specific assumption is absent.",
    )
    lower_return_pct: float | None = Field(default=None, gt=-100)
    higher_return_pct: float | None = Field(default=None, gt=-100)
    additional_sip_return_pct: float | None = Field(
        default=None,
        gt=-100,
        description="Annual assumption used to calculate the additional SIP; defaults to expected_return_pct.",
    )
    assume_unknown_sip_zero: bool = Field(
        default=False,
        description="Must be explicitly true to treat unknown existing SIP amounts as zero for a complete goal calculation.",
    )

    @model_validator(mode="after")
    def validate_goal(self):
        if (self.duration_months is None) == (self.target_date is None):
            raise ValueError("Provide exactly one of duration_months or target_date")
        if self.target_date is not None and self.target_date <= date.today():
            raise ValueError("target_date must be in the future")
        if self.lower_return_pct is not None and self.lower_return_pct >= self.expected_return_pct:
            raise ValueError("lower_return_pct must be below expected_return_pct")
        if self.higher_return_pct is not None and self.higher_return_pct <= self.expected_return_pct:
            raise ValueError("higher_return_pct must be above expected_return_pct")
        return self


class MutualFundAnalysisRequest(BaseModel):
    holdings: list[MutualFundHoldingRequest] = Field(min_length=1)
    projection: MutualFundProjectionRequest | None = None
    goal: MutualFundGoalRequest | None = None
    transactions: list[MutualFundTransactionRequest] | None = None
    reporting_currency: CurrencyCode | None = None
    analysis_question: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def same_client(self):
        if len({holding.client_id for holding in self.holdings}) != 1:
            raise ValueError("All holdings must belong to the same client_id")
        return self

    @field_validator("analysis_question", mode="before")
    @classmethod
    def clean_question(cls, value):
        if value is None:
            return None
        value = str(value).strip()
        return value or None

class MutualFundPortfolioRequest(MutualFundAnalysisRequest):
    """Request contract for complete MF and projection analysis."""


# ---------------------------------------------------------------------------
# Standalone projection contract (kept for backward compatibility)
# ---------------------------------------------------------------------------

class MutualFundProjectionRequest(BaseModel):
    projection_type: ProjectionType
    target_amount: float | None = Field(default=None, gt=0)
    monthly_sip_amount: float | None = Field(default=None, ge=0)
    current_investment: float | None = Field(default=None, ge=0)
    duration_months: int | None = Field(default=None, gt=0)
    expected_return_pct: float | None = Field(default=None, gt=-100)
    analysis_question: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_inputs(self):
        required = {
            ProjectionType.FUTURE_VALUE: ("current_investment", "duration_months", "expected_return_pct"),
            ProjectionType.REQUIRED_SIP: ("target_amount", "current_investment", "duration_months", "expected_return_pct"),
            ProjectionType.TIME_TO_TARGET: ("target_amount", "current_investment", "expected_return_pct"),
            ProjectionType.LUMPSUM_GROWTH: ("current_investment", "duration_months", "expected_return_pct"),
        }[self.projection_type]
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(f"Missing projection fields: {', '.join(missing)}")
        return self

    @field_validator("analysis_question", mode="before")
    @classmethod
    def clean_question(cls, value):
        if value is None:
            return None
        value = str(value).strip()
        return value or None


# ---------------------------------------------------------------------------
# Stateless monitoring
# ---------------------------------------------------------------------------

class MonitoringRuleType(str, Enum):
    PRICE_ABOVE = "PRICE_ABOVE"
    PRICE_BELOW = "PRICE_BELOW"
    LOSS_PCT_ABOVE = "LOSS_PCT_ABOVE"
    GAIN_PCT_ABOVE = "GAIN_PCT_ABOVE"
    NAV_CHANGE_PCT = "NAV_CHANGE_PCT"
    MF_LOSS_PCT_ABOVE = "MF_LOSS_PCT_ABOVE"


class MonitoringAssetType(str, Enum):
    STOCK = "stock"
    MUTUAL_FUND = "mutual_fund"


class MonitoringRule(BaseModel):
    rule_id: str = Field(min_length=1, max_length=100)
    rule_type: MonitoringRuleType
    threshold: float = Field(ge=0)

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def valid_threshold(self):
        if not isfinite(self.threshold):
            raise ValueError("threshold must be a finite number")
        if self.rule_type in {MonitoringRuleType.PRICE_ABOVE, MonitoringRuleType.PRICE_BELOW} and self.threshold <= 0:
            raise ValueError("Price thresholds must be greater than zero")
        return self


class MonitoringAsset(BaseModel):
    asset_type: MonitoringAssetType = MonitoringAssetType.STOCK
    symbol: str | None = None
    scheme_code: str | None = None
    scheme_name: str | None = None
    exchange: str | None = None
    quantity: float | None = Field(default=None, gt=0)
    buy_price: float | None = Field(default=None, gt=0)
    units: float | None = Field(default=None, gt=0)
    invested_value: float | None = Field(default=None, gt=0)
    rules: list[MonitoringRule] = Field(min_length=1)

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def validate_asset(self):
        if self.asset_type == MonitoringAssetType.STOCK:
            if not self.symbol:
                raise ValueError("symbol is required for stock assets")
            if any(rule.rule_type in {MonitoringRuleType.NAV_CHANGE_PCT, MonitoringRuleType.MF_LOSS_PCT_ABOVE} for rule in self.rules):
                raise ValueError("NAV_CHANGE_PCT and MF_LOSS_PCT_ABOVE are mutual-fund-only rules")
            if any(rule.rule_type in {MonitoringRuleType.LOSS_PCT_ABOVE, MonitoringRuleType.GAIN_PCT_ABOVE} for rule in self.rules):
                if self.quantity is None or self.buy_price is None:
                    raise ValueError("quantity and buy_price are required for stock loss/gain rules")
        else:
            if not (self.scheme_code or self.scheme_name):
                raise ValueError("scheme_code or scheme_name is required for mutual-fund assets")
            needs_return = any(
                rule.rule_type in {
                    MonitoringRuleType.LOSS_PCT_ABOVE,
                    MonitoringRuleType.GAIN_PCT_ABOVE,
                    MonitoringRuleType.MF_LOSS_PCT_ABOVE,
                }
                for rule in self.rules
            )
            if needs_return and (self.invested_value is None or self.units is None):
                raise ValueError("units and invested_value are required for mutual-fund loss/gain rules")
        return self


class StatelessMonitoringRequest(BaseModel):
    client_id: str = Field(min_length=1)
    assets: list[MonitoringAsset] = Field(min_length=1, max_length=200)

    model_config = ConfigDict(str_strip_whitespace=True)


MutualFundAnalysisRequest.model_rebuild()
MutualFundPortfolioRequest.model_rebuild()