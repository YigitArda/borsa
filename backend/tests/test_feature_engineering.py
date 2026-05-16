from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_financial_features_are_point_in_time():
    from app.database import Base
    from app.models.financial import FinancialMetric
    from app.models.stock import Stock
    from app.services.financial_data import FinancialDataService

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Stock.__table__, FinancialMetric.__table__])

    session = Session(engine)
    try:
        stock = Stock(ticker="AAPL")
        session.add(stock)
        session.commit()
        session.refresh(stock)

        session.add_all(
            [
                FinancialMetric(
                    stock_id=stock.id,
                    fiscal_period_end=date(2025, 3, 31),
                    as_of_date=date(2025, 4, 15),
                    metric_name="forward_pe",
                    value=30.0,
                    is_ttm=True,
                    data_source="yfinance",
                ),
                FinancialMetric(
                    stock_id=stock.id,
                    fiscal_period_end=date(2025, 3, 31),
                    as_of_date=date(2025, 5, 15),
                    metric_name="forward_pe",
                    value=25.0,
                    is_ttm=True,
                    data_source="yfinance",
                ),
                FinancialMetric(
                    stock_id=stock.id,
                    fiscal_period_end=date(2025, 3, 31),
                    as_of_date=date(2025, 5, 20),
                    metric_name="pe_ratio",
                    value=18.0,
                    is_ttm=True,
                    data_source="yfinance",
                ),
            ]
        )
        session.commit()

        service = FinancialDataService(session)

        april_features = service.get_financial_features(stock.id, date(2025, 4, 30))
        assert april_features["forward_pe"] == 30.0
        assert "pe_ratio" not in april_features

        may_features = service.get_financial_features(stock.id, date(2025, 5, 31))
        assert may_features["forward_pe"] == 25.0
        assert may_features["pe_ratio"] == 18.0
    finally:
        session.close()
