from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MONEY = Numeric(20, 4, asdecimal=True)
RATE = Numeric(20, 10, asdecimal=True)
QUANTITY = Numeric(28, 10, asdecimal=True)


class Base(DeclarativeBase):
    pass


class ScheduleType(str, Enum):
    ONE_TIME = "one_time"
    WEEKLY = "weekly"
    EVERY_N_WEEKS = "every_n_weeks"
    MONTHLY = "monthly"
    EVERY_N_MONTHS = "every_n_months"
    YEARLY = "yearly"
    SPECIFIC_DATES = "specific_dates"


class WeekendPolicy(str, Enum):
    EXACT = "exact"
    PREVIOUS_BUSINESS_DAY = "previous_business_day"
    NEXT_BUSINESS_DAY = "next_business_day"


class Currency(Base):
    __tablename__ = "currencies"
    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    symbol: Mapped[str] = mapped_column(String(8))
    decimals: Mapped[int] = mapped_column(Integer, default=2)


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (UniqueConstraint("base_currency", "quote_currency", "rate_date", "source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    base_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    quote_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    rate: Mapped[Decimal] = mapped_column(RATE)
    rate_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(24), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    account_type: Mapped[str] = mapped_column(String(32))
    purpose: Mapped[str] = mapped_column(String(16), default="personal", server_default="personal")
    institution: Mapped[str | None] = mapped_column(String(120))
    # Asset-account balances are signed: overdraft is negative. Standalone debt
    # remains a positive amount owed in Debt.current_balance.
    current_balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"), default="CAD")
    include_in_cash: Mapped[bool] = mapped_column(Boolean, default=True)
    include_in_net_worth: Mapped[bool] = mapped_column(Boolean, default=True)
    overdraft_limit: Mapped[Decimal | None] = mapped_column(MONEY)
    overdraft_interest_rate: Mapped[Decimal | None] = mapped_column(RATE)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    snapshots: Mapped[list[BalanceSnapshot]] = relationship(back_populates="account", cascade="all, delete-orphan")


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    balance: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    snapshot_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    account: Mapped[Account] = relationship(back_populates="snapshots")


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    category_type: Mapped[str] = mapped_column(String(32), default="expense")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_type: Mapped[str] = mapped_column(String(32))
    anchor_date: Mapped[date | None] = mapped_column(Date)
    interval: Mapped[int] = mapped_column(Integer, default=1)
    day_of_month: Mapped[int | None] = mapped_column(Integer)
    month_of_year: Mapped[int | None] = mapped_column(Integer)
    weekday: Mapped[int | None] = mapped_column(Integer)
    nth_weekday: Mapped[int | None] = mapped_column(Integer)
    weekend_policy: Mapped[str] = mapped_column(String(32), default=WeekendPolicy.EXACT.value)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    dates: Mapped[list[ScheduleDate]] = relationship(back_populates="schedule", cascade="all, delete-orphan")


class ScheduleDate(Base):
    __tablename__ = "schedule_dates"
    __table_args__ = (UniqueConstraint("schedule_id", "occurrence_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"))
    occurrence_date: Mapped[date] = mapped_column(Date)
    schedule: Mapped[Schedule] = relationship(back_populates="dates")


class IncomeSource(Base):
    __tablename__ = "income_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id"))
    destination_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    purpose: Mapped[str] = mapped_column(String(16), default="personal", server_default="personal")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class RecurringExpense(Base):
    __tablename__ = "recurring_expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    priority: Mapped[str] = mapped_column(String(24), default="important")
    payment_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    backup_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    funding_strategy: Mapped[str] = mapped_column(String(32), default="primary_then_backup")
    purpose: Mapped[str] = mapped_column(String(16), default="personal", server_default="personal")
    payment_debt_id: Mapped[int | None] = mapped_column(ForeignKey("debts.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class Debt(Base):
    __tablename__ = "debts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    debt_type: Mapped[str] = mapped_column(String(32))
    current_balance: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    interest_rate: Mapped[Decimal | None] = mapped_column(RATE)
    credit_limit: Mapped[Decimal | None] = mapped_column(MONEY)
    minimum_payment: Mapped[Decimal | None] = mapped_column(MONEY)
    payment_schedule_id: Mapped[int | None] = mapped_column(ForeignKey("schedules.id"))
    payment_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class DebtSnapshot(Base):
    __tablename__ = "debt_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    debt_id: Mapped[int] = mapped_column(ForeignKey("debts.id", ondelete="CASCADE"))
    balance: Mapped[Decimal] = mapped_column(MONEY)
    snapshot_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OneTimeEvent(Base):
    __tablename__ = "one_time_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    event_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    backup_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    funding_strategy: Mapped[str] = mapped_column(String(32), default="primary_then_backup")
    purpose: Mapped[str] = mapped_column(String(16), default="personal", server_default="personal")
    payment_debt_id: Mapped[int | None] = mapped_column(ForeignKey("debts.id"))
    event_type: Mapped[str] = mapped_column(String(16))
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class Deposit(Base):
    """Scheduled movement of money into a bank or investment account. Plans only."""
    __tablename__ = "deposits"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id"))
    source_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    destination_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    destination_investment_id: Mapped[int | None] = mapped_column(ForeignKey("investment_accounts.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)


class InvestmentAccount(Base):
    __tablename__ = "investment_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    account_type: Mapped[str] = mapped_column(String(32))
    institution: Mapped[str | None] = mapped_column(String(120))
    cash_balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    cash_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"), default="CAD")
    include_in_net_worth: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InvestmentHolding(Base):
    __tablename__ = "investment_holdings"
    id: Mapped[int] = mapped_column(primary_key=True)
    investment_account_id: Mapped[int] = mapped_column(ForeignKey("investment_accounts.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(120))
    asset_type: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    average_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    cost_currency: Mapped[str | None] = mapped_column(ForeignKey("currencies.code"))
    quote_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SecurityPrice(Base):
    __tablename__ = "security_prices"
    __table_args__ = (UniqueConstraint("symbol", "price_date", "source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    price: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    price_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(24), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InvestmentSnapshot(Base):
    __tablename__ = "investment_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    investment_account_id: Mapped[int] = mapped_column(ForeignKey("investment_accounts.id", ondelete="CASCADE"))
    market_value: Mapped[Decimal] = mapped_column(MONEY)
    reporting_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    cash_balance: Mapped[Decimal] = mapped_column(MONEY)
    snapshot_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MaterialAsset(Base):
    __tablename__ = "material_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    asset_type: Mapped[str] = mapped_column(String(32), default="other")
    current_value: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"), default="CAD")
    include_in_net_worth: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    snapshots: Mapped[list[MaterialAssetSnapshot]] = relationship(cascade="all, delete-orphan")


class MaterialAssetSnapshot(Base):
    __tablename__ = "material_asset_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    material_asset_id: Mapped[int] = mapped_column(ForeignKey("material_assets.id", ondelete="CASCADE"))
    value: Mapped[Decimal] = mapped_column(MONEY)
    snapshot_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SpendingEntry(Base):
    """Optional aggregate or notable spending record; itemized entry is never required."""
    __tablename__ = "spending_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"), default="CAD")
    entry_type: Mapped[str] = mapped_column(String(32), default="general")
    description: Mapped[str | None] = mapped_column(String(160))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)

