from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, Date, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Instrument(Base):
    __tablename__="instrument"
    id: Mapped[int]=mapped_column(primary_key=True); symbol: Mapped[str]=mapped_column(String(32), unique=True, index=True); local_code: Mapped[str|None]=mapped_column(String(16)); name: Mapped[str|None]=mapped_column(String(256)); instrument_type: Mapped[str]=mapped_column(String(20)); exchange: Mapped[str|None]=mapped_column(String(20)); currency: Mapped[str|None]=mapped_column(String(10)); sector: Mapped[str|None]=mapped_column(String(128)); industry: Mapped[str|None]=mapped_column(String(128)); timezone: Mapped[str|None]=mapped_column(String(64)); is_active: Mapped[bool]=mapped_column(Boolean, default=True); created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow); updated_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Universe(Base):
    __tablename__="universe"
    id: Mapped[int]=mapped_column(primary_key=True); code: Mapped[str]=mapped_column(String(80), unique=True); name: Mapped[str]=mapped_column(String(256)); description: Mapped[str|None]=mapped_column(Text); universe_type: Mapped[str]=mapped_column(String(40)); as_of_date: Mapped[str|None]=mapped_column(String(10)); is_active: Mapped[bool]=mapped_column(Boolean, default=True); metadata_json: Mapped[str|None]=mapped_column(Text); created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow); updated_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class UniverseInstrument(Base):
    __tablename__="universe_instrument"
    id: Mapped[int]=mapped_column(primary_key=True); universe_id: Mapped[int]=mapped_column(ForeignKey("universe.id")); instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id")); membership_type: Mapped[str]=mapped_column(String(40)); source: Mapped[str|None]=mapped_column(String(80)); valid_from: Mapped[str|None]=mapped_column(String(10)); valid_to: Mapped[str|None]=mapped_column(String(10)); metadata_json: Mapped[str|None]=mapped_column(Text); created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)
    __table_args__=(UniqueConstraint("universe_id","instrument_id"),)

class FundMetadataSnapshot(Base):
    __tablename__="fund_metadata_snapshot"
    id: Mapped[int]=mapped_column(primary_key=True)
    fund_instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id"), index=True)
    as_of_date: Mapped[str]=mapped_column(String(10), index=True)
    source: Mapped[str]=mapped_column(String(80))
    source_url: Mapped[str|None]=mapped_column(String(512))
    fetched_at: Mapped[datetime]=mapped_column(DateTime)
    is_official: Mapped[bool]=mapped_column(Boolean, default=False)
    status: Mapped[str]=mapped_column(String(32), default="SUCCESS")
    payload_json: Mapped[str|None]=mapped_column(Text)
    error_message: Mapped[str|None]=mapped_column(Text)
    __table_args__=(UniqueConstraint("fund_instrument_id","as_of_date","source"),)

class FundNavObservation(Base):
    __tablename__="fund_nav_observation"
    id: Mapped[int]=mapped_column(primary_key=True)
    fund_instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id"), index=True)
    nav_date: Mapped[str]=mapped_column(String(10), index=True)
    unit_nav: Mapped[float|None]=mapped_column(Float)
    cumulative_nav: Mapped[float|None]=mapped_column(Float)
    daily_change_pct: Mapped[float|None]=mapped_column(Float)
    source: Mapped[str]=mapped_column(String(80))
    source_url: Mapped[str|None]=mapped_column(String(512))
    fetched_at: Mapped[datetime]=mapped_column(DateTime)
    available_at: Mapped[datetime|None]=mapped_column(DateTime)
    status: Mapped[str]=mapped_column(String(32), default="SUCCESS")
    payload_json: Mapped[str|None]=mapped_column(Text)
    error_message: Mapped[str|None]=mapped_column(Text)
    __table_args__=(UniqueConstraint("fund_instrument_id","nav_date","source"),)

class EtfStatusObservation(Base):
    __tablename__="etf_status_observation"
    id: Mapped[int]=mapped_column(primary_key=True)
    etf_instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id"), index=True)
    observed_date: Mapped[str]=mapped_column(String(10), index=True)
    observed_at: Mapped[datetime]=mapped_column(DateTime)
    nav_date: Mapped[str|None]=mapped_column(String(10))
    unit_nav: Mapped[float|None]=mapped_column(Float)
    market_price: Mapped[float|None]=mapped_column(Float)
    iopv: Mapped[float|None]=mapped_column(Float)
    discount_rate_pct: Mapped[float|None]=mapped_column(Float)
    shares: Mapped[float|None]=mapped_column(Float)
    amount: Mapped[float|None]=mapped_column(Float)
    circulating_market_cap: Mapped[float|None]=mapped_column(Float)
    total_market_cap: Mapped[float|None]=mapped_column(Float)
    source: Mapped[str]=mapped_column(String(80))
    fetched_at: Mapped[datetime]=mapped_column(DateTime)
    status: Mapped[str]=mapped_column(String(32), default="SUCCESS")
    payload_json: Mapped[str|None]=mapped_column(Text)
    error_message: Mapped[str|None]=mapped_column(Text)
    __table_args__=(UniqueConstraint("etf_instrument_id","observed_at","source"),)

class FundEvent(Base):
    __tablename__="fund_event"
    id: Mapped[int]=mapped_column(primary_key=True)
    fund_instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id"), index=True)
    event_date: Mapped[str]=mapped_column(String(10), index=True)
    available_at: Mapped[datetime]=mapped_column(DateTime, index=True)
    title: Mapped[str]=mapped_column(String(512))
    url: Mapped[str|None]=mapped_column(String(1024))
    source: Mapped[str]=mapped_column(String(80), index=True)
    source_level: Mapped[str]=mapped_column(String(32))
    event_type: Mapped[str]=mapped_column(String(64))
    confirmation_status: Mapped[str]=mapped_column(String(32))
    already_reflected_status: Mapped[str]=mapped_column(String(32), default="UNKNOWN")
    content_hash: Mapped[str]=mapped_column(String(64), index=True)
    dedup_key: Mapped[str]=mapped_column(String(64), unique=True, index=True)
    summary: Mapped[str|None]=mapped_column(Text)
    fetched_at: Mapped[datetime]=mapped_column(DateTime)
    payload_json: Mapped[str|None]=mapped_column(Text)

class FundEventSyncState(Base):
    __tablename__="fund_event_sync_state"
    id: Mapped[int]=mapped_column(primary_key=True)
    fund_instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id"), index=True)
    source: Mapped[str]=mapped_column(String(80))
    last_successful_event_date: Mapped[str|None]=mapped_column(String(10))
    last_checked_at: Mapped[datetime|None]=mapped_column(DateTime)
    status: Mapped[str]=mapped_column(String(32))
    error_message: Mapped[str|None]=mapped_column(Text)
    __table_args__=(UniqueConstraint("fund_instrument_id","source"),)

class SectorFundBacktestRun(Base):
    __tablename__="sector_fund_backtest_run"
    run_id: Mapped[str]=mapped_column(String(64), primary_key=True)
    fund_code: Mapped[str]=mapped_column(String(16), index=True)
    requested_end_date: Mapped[str]=mapped_column(String(10))
    feature_version: Mapped[str]=mapped_column(String(64))
    scoring_version: Mapped[str]=mapped_column(String(64))
    label_version: Mapped[str]=mapped_column(String(64))
    sample_start_date: Mapped[str|None]=mapped_column(String(10))
    sample_end_date: Mapped[str|None]=mapped_column(String(10))
    sample_count: Mapped[int]=mapped_column(Integer, default=0)
    status: Mapped[str]=mapped_column(String(32))
    input_hash: Mapped[str]=mapped_column(String(64), index=True)
    config_json: Mapped[str]=mapped_column(Text)
    result_json: Mapped[str|None]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)

class SectorFundBacktestSample(Base):
    __tablename__="sector_fund_backtest_sample"
    id: Mapped[int]=mapped_column(primary_key=True)
    run_id: Mapped[str]=mapped_column(ForeignKey("sector_fund_backtest_run.run_id"), index=True)
    analysis_date: Mapped[str]=mapped_column(String(10), index=True)
    weight_snapshot_id: Mapped[int]=mapped_column(ForeignKey("universe_snapshot.id"))
    weight_snapshot_date: Mapped[str]=mapped_column(String(10))
    core_score: Mapped[float|None]=mapped_column(Float)
    short_score: Mapped[float|None]=mapped_column(Float)
    forward_1d_pct: Mapped[float|None]=mapped_column(Float)
    forward_3d_pct: Mapped[float|None]=mapped_column(Float)
    label_1d: Mapped[str|None]=mapped_column(String(16))
    label_3d: Mapped[str|None]=mapped_column(String(16))
    prediction_json: Mapped[str|None]=mapped_column(Text)
    brier_1d: Mapped[float|None]=mapped_column(Float)
    brier_3d: Mapped[float|None]=mapped_column(Float)
    feature_json: Mapped[str]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)
    __table_args__=(UniqueConstraint("run_id","analysis_date"),)

class UniverseSnapshot(Base):
    __tablename__="universe_snapshot"
    id: Mapped[int]=mapped_column(primary_key=True)
    universe_id: Mapped[int]=mapped_column(ForeignKey("universe.id"), index=True)
    as_of_date: Mapped[str]=mapped_column(String(10), index=True)
    source: Mapped[str]=mapped_column(String(80))
    source_url: Mapped[str|None]=mapped_column(String(512))
    fetched_at: Mapped[datetime]=mapped_column(DateTime)
    status: Mapped[str]=mapped_column(String(32), default="SUCCESS")
    payload_json: Mapped[str|None]=mapped_column(Text)
    error_message: Mapped[str|None]=mapped_column(Text)
    __table_args__=(UniqueConstraint("universe_id","as_of_date","source"),)

class UniverseConstituentWeight(Base):
    __tablename__="universe_constituent_weight"
    id: Mapped[int]=mapped_column(primary_key=True)
    snapshot_id: Mapped[int]=mapped_column(ForeignKey("universe_snapshot.id"), index=True)
    instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id"), index=True)
    rank: Mapped[int|None]=mapped_column(Integer)
    weight_pct: Mapped[float|None]=mapped_column(Float)
    source: Mapped[str]=mapped_column(String(80))
    __table_args__=(UniqueConstraint("snapshot_id","instrument_id"),)

class InstrumentClassificationSnapshot(Base):
    __tablename__="instrument_classification_snapshot"
    id: Mapped[int]=mapped_column(primary_key=True)
    instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id"), index=True)
    as_of_date: Mapped[str]=mapped_column(String(10), index=True)
    scheme: Mapped[str]=mapped_column(String(48), index=True)
    source: Mapped[str]=mapped_column(String(80))
    source_url: Mapped[str|None]=mapped_column(String(512))
    fetched_at: Mapped[datetime]=mapped_column(DateTime)
    status: Mapped[str]=mapped_column(String(32), default="SUCCESS")
    classification_json: Mapped[str|None]=mapped_column(Text)
    error_message: Mapped[str|None]=mapped_column(Text)
    __table_args__=(UniqueConstraint("instrument_id","as_of_date","scheme","source"),)

class FundHoldingReport(Base):
    __tablename__="fund_holding_report"
    id: Mapped[int]=mapped_column(primary_key=True); fund_instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id")); report_period_end: Mapped[str]=mapped_column(String(10)); published_date: Mapped[str]=mapped_column(String(10)); published_at: Mapped[datetime|None]=mapped_column(DateTime); disclosed_weight: Mapped[float|None]=mapped_column(Float); holdings_count: Mapped[int]=mapped_column(Integer)
    __table_args__=(UniqueConstraint("fund_instrument_id","report_period_end"),)

class FundHoldingPosition(Base):
    __tablename__="fund_holding_position"
    id: Mapped[int]=mapped_column(primary_key=True); report_id: Mapped[int]=mapped_column(ForeignKey("fund_holding_report.id")); stock_instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id")); rank: Mapped[int]=mapped_column(Integer); weight_pct: Mapped[float|None]=mapped_column(Float); shares: Mapped[float|None]=mapped_column(Float); market_value: Mapped[float|None]=mapped_column(Float)

class FundInstrumentRelation(Base):
    __tablename__="fund_instrument_relation"
    id: Mapped[int]=mapped_column(primary_key=True); fund_instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id")); related_instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id")); relationship_type: Mapped[str]=mapped_column(String(40)); weight_pct: Mapped[float|None]=mapped_column(Float); report_period_end: Mapped[str]=mapped_column(String(10)); published_date: Mapped[str]=mapped_column(String(10))

class IngestionRun(Base):
    __tablename__="ingestion_run"
    run_id: Mapped[str]=mapped_column(String(64), primary_key=True); started_at: Mapped[datetime]=mapped_column(DateTime); completed_at: Mapped[datetime|None]=mapped_column(DateTime); provider: Mapped[str]=mapped_column(String(32)); requested_symbols: Mapped[int]=mapped_column(Integer, default=0); success_symbols: Mapped[int]=mapped_column(Integer, default=0); failed_symbols: Mapped[int]=mapped_column(Integer, default=0); status: Mapped[str]=mapped_column(String(32)); yfinance_version: Mapped[str|None]=mapped_column(String(32)); schema_version: Mapped[str|None]=mapped_column(String(32)); config_json: Mapped[str|None]=mapped_column(Text)

class IngestionRunItem(Base):
    __tablename__="ingestion_run_item"
    id: Mapped[int]=mapped_column(primary_key=True); run_id: Mapped[str]=mapped_column(ForeignKey("ingestion_run.run_id")); symbol: Mapped[str]=mapped_column(String(32)); dataset_type: Mapped[str]=mapped_column(String(40)); status: Mapped[str]=mapped_column(String(32)); record_count: Mapped[int]=mapped_column(Integer, default=0); inserted_count: Mapped[int]=mapped_column(Integer, default=0); skipped_duplicate_count: Mapped[int]=mapped_column(Integer, default=0); first_data_time: Mapped[str|None]=mapped_column(String(64)); latest_data_time: Mapped[str|None]=mapped_column(String(64)); elapsed_ms: Mapped[int|None]=mapped_column(Integer); quality_metrics_json: Mapped[str|None]=mapped_column(Text); error_type: Mapped[str|None]=mapped_column(String(128)); error_message: Mapped[str|None]=mapped_column(Text)

class MarketBarObservation(Base):
    __tablename__="market_bar_observation"
    id: Mapped[int]=mapped_column(primary_key=True); instrument_id: Mapped[int]=mapped_column(ForeignKey("instrument.id"), index=True); interval: Mapped[str]=mapped_column(String(8)); bar_time: Mapped[datetime]=mapped_column(DateTime, index=True); market_date: Mapped[str|None]=mapped_column(String(10), index=True); open: Mapped[float|None]=mapped_column(Float); high: Mapped[float|None]=mapped_column(Float); low: Mapped[float|None]=mapped_column(Float); close: Mapped[float|None]=mapped_column(Float); adjusted_close: Mapped[float|None]=mapped_column(Float); volume: Mapped[float|None]=mapped_column(Float); amount: Mapped[float|None]=mapped_column(Float); dividends: Mapped[float|None]=mapped_column(Float); stock_splits: Mapped[float|None]=mapped_column(Float); capital_gains: Mapped[float|None]=mapped_column(Float); is_final: Mapped[bool]=mapped_column(Boolean, default=True); provider: Mapped[str]=mapped_column(String(32)); upstream_group: Mapped[str]=mapped_column(String(64)); source_event_time: Mapped[datetime|None]=mapped_column(DateTime); available_at: Mapped[datetime]=mapped_column(DateTime); fetched_at: Mapped[datetime]=mapped_column(DateTime); payload_hash: Mapped[str]=mapped_column(String(64), index=True); run_id: Mapped[str]=mapped_column(String(64)); created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)
    __table_args__=(UniqueConstraint("instrument_id","interval","bar_time","provider","payload_hash"),)

class FundDataObservation(Base):
    """Auditable non-price data used by the fund analysis layer."""
    __tablename__="fund_data_observation"
    id: Mapped[int]=mapped_column(primary_key=True)
    instrument_id: Mapped[int|None]=mapped_column(ForeignKey("instrument.id"), index=True)
    fund_code: Mapped[str|None]=mapped_column(String(16), index=True)
    dataset_type: Mapped[str]=mapped_column(String(64), index=True)
    field_name: Mapped[str]=mapped_column(String(96), index=True)
    applicable_date: Mapped[str|None]=mapped_column(String(10), index=True)
    published_date: Mapped[str|None]=mapped_column(String(10), index=True)
    available_at: Mapped[datetime|None]=mapped_column(DateTime, index=True)
    source_level: Mapped[str]=mapped_column(String(16))
    source: Mapped[str]=mapped_column(String(96))
    source_url: Mapped[str|None]=mapped_column(String(1024))
    confirmation_status: Mapped[str]=mapped_column(String(32))
    payload_hash: Mapped[str]=mapped_column(String(64), index=True)
    value_json: Mapped[str]=mapped_column(Text)
    fetched_at: Mapped[datetime]=mapped_column(DateTime)
    status: Mapped[str]=mapped_column(String(32), default="SUCCESS")
    error_message: Mapped[str|None]=mapped_column(Text)
    __table_args__=(UniqueConstraint("instrument_id","dataset_type","field_name","applicable_date","source","payload_hash"),)

class McpWebObservation(Base):
    """Raw, traceable documents supplied by an MCP web resolver.

    These rows are deliberately isolated from both ``market_bar_observation``
    (AKShare/history bars) and ``fund_data_observation`` (derived or API
    observations).  A report may derive a result from an approved MCP row,
    but it must keep the original document and its provenance here.
    """
    __tablename__="mcp_web_observation"
    id: Mapped[int]=mapped_column(primary_key=True)
    instrument_id: Mapped[int|None]=mapped_column(ForeignKey("instrument.id"), index=True)
    fund_code: Mapped[str|None]=mapped_column(String(16), index=True)
    dataset_type: Mapped[str]=mapped_column(String(64), index=True)
    field_name: Mapped[str]=mapped_column(String(96), index=True)
    applicable_date: Mapped[str|None]=mapped_column(String(10), index=True)
    published_date: Mapped[str|None]=mapped_column(String(10), index=True)
    available_at: Mapped[datetime|None]=mapped_column(DateTime, index=True)
    source_level: Mapped[str]=mapped_column(String(16))
    source: Mapped[str]=mapped_column(String(96))
    source_url: Mapped[str|None]=mapped_column(String(1024))
    confirmation_status: Mapped[str]=mapped_column(String(32))
    content_hash: Mapped[str]=mapped_column(String(64), index=True)
    payload_json: Mapped[str|None]=mapped_column(Text)
    fetched_at: Mapped[datetime]=mapped_column(DateTime)
    status: Mapped[str]=mapped_column(String(32), default="SUCCESS")
    error_message: Mapped[str|None]=mapped_column(Text)
    __table_args__=(UniqueConstraint("instrument_id","dataset_type","field_name","applicable_date","source","content_hash"),)

def import_models(): return (Instrument, Universe, UniverseInstrument, FundMetadataSnapshot, FundNavObservation, EtfStatusObservation, FundEvent, FundEventSyncState, SectorFundBacktestRun, SectorFundBacktestSample, UniverseSnapshot, UniverseConstituentWeight, InstrumentClassificationSnapshot, FundHoldingReport, FundHoldingPosition, FundInstrumentRelation, IngestionRun, IngestionRunItem, MarketBarObservation, FundDataObservation, McpWebObservation)
