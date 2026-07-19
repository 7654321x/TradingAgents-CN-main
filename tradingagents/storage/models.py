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

def import_models(): return (Instrument, Universe, UniverseInstrument, FundHoldingReport, FundHoldingPosition, FundInstrumentRelation, IngestionRun, IngestionRunItem, MarketBarObservation)
