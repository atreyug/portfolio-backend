from pydantic import BaseModel, ConfigDict, Field


class MonitoringHoldingRequest(BaseModel):
    client_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    quantity: float | None = Field(default=None, gt=0)
    buy_price: float | None = Field(default=None, gt=0)
    exchange: str | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class MonitoringCheckRequest(MonitoringHoldingRequest):
    # Rules are deliberately not part of this request. They belong to a
    # separately managed monitoring configuration.
    pass
