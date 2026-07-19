from tradingagents.extensions.sector_fund import ALL_MARKET_SYMBOLS, STOCK_SYMBOLS, PROXY_SYMBOLS, FUND_CODES, UNIQUE_STOCKS
from tradingagents.storage.db import get_engine, init_db
from tradingagents.storage.service import ingest_fund_holdings
from sqlalchemy.orm import Session
from tradingagents.storage.models import Instrument, FundHoldingPosition, FundInstrumentRelation

def test_seed_statistics():
    assert len(FUND_CODES)==3; assert len(STOCK_SYMBOLS)==27; assert len(PROXY_SYMBOLS)==1; assert len(ALL_MARKET_SYMBOLS)==28
    assert PROXY_SYMBOLS==("589130.SS",)

def test_duplicate_holdings_share_one_instrument():
    assert len(UNIQUE_STOCKS)==27

def test_import_relations_and_proxy():
    engine=init_db(get_engine("sqlite://")); counts=ingest_fund_holdings(engine=engine)
    assert counts=={"funds":3,"stocks":27,"etfs":1,"reports":3,"positions":30,"relations":1}
    with Session(engine) as s:
        assert s.query(Instrument).count()==33
        assert s.query(FundHoldingPosition).count()==30
        assert s.query(FundInstrumentRelation).count()==1
