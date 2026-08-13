# Private Personal Finance Tracker

## Full Design & Implementation Specification

**Target:** V0.1 with architecture prepared for later analytics, investment tracking, visualization, imports, and automation.

---

# 1. Project Goal

Build a **local-only Linux desktop personal finance application** for a single user.

The application should provide a centralized view of:

- Current cash
- Bank-account balances
- Savings
- Credit-card balances
- Student debt
- Other debt
- Income
- Recurring bills
- One-time expenses/income
- Exact payment timing
- Future cash flow
- TFSA holdings
- FHSA holdings
- Other investment accounts
- Stock/ETF holdings
- Net worth
- Historical financial progress

The primary goal is:

> Make it very easy to understand what money is available, what money is already committed, what is owned, what is owed, and how those numbers are changing over time.

The application is **not intended to enforce frugality**.

The user determines which expenses are worthwhile.

The software should provide information and projections rather than moral judgments about spending.

---

# 2. Product Philosophy

The application should answer three broad categories of questions.

## Cash Flow

> Can I afford this?

Examples:

- How much cash do I have?
- What bills occur before my next paycheque?
- How low will my balance get before payday?
- What does the next 30/60/90 days look like?
- Which months have three biweekly payments?
- How much money is actually unallocated?

## Balance Sheet

> What do I own and owe?

Examples:

- How much cash do I have?
- What is my total investment value?
- How much student debt remains?
- What is my total debt?
- What is my current net worth?

## Historical Progress

> Am I moving in the right direction?

Examples:

- Is my debt decreasing?
- Are my investments increasing?
- How has my net worth changed?
- Is my discretionary spending increasing?
- How much have I contributed to savings/investments?

These concepts should remain related but distinct.

In particular:

> Net worth is not the same thing as spendable cash.

---

# 3. Core Architectural Principle

The core application should behave as a:

> **Dated cash-flow and personal balance-sheet engine with a Qt GUI layered on top.**

For recurring financial activity, the authoritative representation should be:

```text
amount + actual occurrence date
```

not:

```text
monthly average
```

Monthly averages are useful for analytics but must be derived from the actual schedule.

For example:

```text
$400 biweekly
```

means:

```text
$400 × 26 = $10,400/year

Average:
$866.67/month
```

But actual budgeting must use:

```text
Aug 14   -$400
Aug 28   -$400
Sep 11   -$400
Sep 25   -$400
Oct 9    -$400
...
```

---

# 4. Technical Stack

Preferred stack:

- Python 3
- PySide6 / Qt
- SQLite
- SQLAlchemy
- Alembic or equivalent lightweight migration system
- Local filesystem storage

Do not introduce cloud infrastructure.

Do not use:

- AWS
- Remote PostgreSQL
- Web server
- Authentication service
- User accounts
- Third-party telemetry
- Cloud synchronization

The application must operate entirely offline except for explicitly optional features such as:

- Market price lookup
- Foreign-exchange rate lookup

These integrations must never be required for the application to function.

---

# 5. Suggested Project Structure

```text
finance_tracker/
├── app/
│   ├── main.py
│   │
│   ├── db/
│   │   ├── database.py
│   │   ├── models.py
│   │   └── migrations/
│   │
│   ├── services/
│   │   ├── schedule_service.py
│   │   ├── projection_service.py
│   │   ├── balance_service.py
│   │   ├── investment_service.py
│   │   ├── currency_service.py
│   │   ├── analytics_service.py
│   │   └── snapshot_service.py
│   │
│   ├── repositories/
│   │   ├── accounts.py
│   │   ├── schedules.py
│   │   ├── investments.py
│   │   └── debts.py
│   │
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── dashboard/
│   │   ├── cashflow/
│   │   ├── accounts/
│   │   ├── income/
│   │   ├── recurring/
│   │   ├── debts/
│   │   ├── investments/
│   │   ├── analytics/
│   │   ├── update_finances/
│   │   └── settings/
│   │
│   └── utils/
│
├── tests/
├── requirements.txt
└── README.md
```

Keep:

```text
database logic
business logic
financial calculations
Qt presentation
```

separated.

Do not place important calculations directly inside Qt widgets.

---

# 6. Currency Model

The application should support multiple currencies from the beginning.

The default/base reporting currency should initially be:

```text
CAD
```

Every monetary entity where currency may differ should store its native currency.

Examples:

```text
Canadian chequing account   CAD
XEQT                        CAD
AAPL                        USD
USD cash                    USD
```

The application should preserve original values in native currency.

Currency conversion should occur only when producing:

- Portfolio totals
- Account totals
- Net worth
- Analytics
- Charts
- Consolidated reporting

---

# 7. Currency Table

Suggested model:

```text
currencies
----------
code
name
symbol
decimals
```

Examples:

```text
CAD
USD
EUR
GBP
```

Only CAD and USD are particularly important initially, but architecture should be generic.

---

# 8. Exchange Rates

Suggested model:

```text
exchange_rates
--------------
id
base_currency
quote_currency
rate
rate_date
source
created_at
```

Example:

```text
base_currency  = USD
quote_currency = CAD
rate           = 1.XXXX
rate_date      = YYYY-MM-DD
source         = manual
```

Possible sources:

```text
manual
api
import
```

V0.1 must permit manual exchange-rate entry.

Automatic exchange-rate retrieval is optional and may be implemented if straightforward.

The application must continue working if automatic retrieval fails.

---

# 9. Currency Conversion Service

Implement conversion centrally.

Conceptually:

```python
convert(
    amount,
    source_currency,
    target_currency,
    rate_date=None
)
```

Do not duplicate conversion logic across UI components.

Example:

```text
AAPL market value:
USD $2,000

USD/CAD:
1.37

Portfolio reporting value:
CAD $2,740
```

Preserve:

```text
USD $2,000
```

as the authoritative security value.

The CAD number is derived.

---

# 10. Historical Currency Conversion

Where historical analytics require conversion, use the closest applicable historical exchange rate where available.

Example:

```text
AAPL value on Jan 15
```

should ideally use the Jan 15 USD/CAD rate rather than today's rate.

This is not essential for initial V0.1 operation.

Architecture should merely support dated FX rates.

If no historical rate is available, clearly indicate that current/latest rate was used.

---

# 11. Accounts

Represents ordinary financial accounts.

Suggested model:

```text
accounts
--------
id
name
account_type
institution
current_balance
currency
include_in_cash
include_in_net_worth
active
created_at
updated_at
```

Possible account types:

```text
checking
savings
cash
credit_card
other
```

Investment accounts should be modeled separately.

---

# 12. Liability Representation

Use a consistent internal convention.

Preferred approach:

Ordinary asset balances:

```text
positive
```

Liabilities/debt balances:

```text
positive amount owed
```

Then calculations explicitly subtract liabilities.

For example:

```text
Chequing        5000
Savings         3000
Student Loan   80000
```

Net worth calculation:

```text
5000 + 3000 - 80000
```

Avoid encoding debt semantics through arbitrary negative database balances.

---

# 13. Balance Snapshots

Historical balances must be preserved.

```text
balance_snapshots
-----------------
id
account_id
balance
currency
snapshot_date
created_at
```

When a current account balance is updated:

1. Update the current value.
2. Insert a snapshot.
3. Preserve previous snapshots.

Do not overwrite historical financial data.

---

# 14. Income Sources

```text
income_sources
--------------
id
name
amount
currency
schedule_id
destination_account_id
active
start_date
end_date
notes
```

Examples:

```text
Salary
Bonus
Freelance payment
Refund
```

Recurring income uses the same scheduling engine as expenses.

---

# 15. Recurring Expenses

```text
recurring_expenses
------------------
id
name
amount
currency
schedule_id
category_id
priority
payment_account_id
active
start_date
end_date
notes
```

Suggested priorities:

```text
essential
important
luxury
expendable
```

Priority represents the user's own judgment.

The application must not automatically classify:

```text
luxury = bad
```

A luxury may intentionally be retained.

---

# 16. Expense Categories

Suggested table:

```text
categories
----------
id
name
category_type
active
created_at
```

Example categories:

```text
Housing
Transportation
Food
Groceries
Restaurants
Utilities
Insurance
Subscriptions
Entertainment
Shopping
Health
Debt
Education
Travel
Miscellaneous
```

Categories must be user-customizable.

Do not hard-code application behavior around these examples.

---

# 17. Scheduling Engine

Scheduling is critical.

The scheduling system must support actual recurrence dates rather than approximate monthly values.

Suggested model:

```text
schedules
---------
id
schedule_type
anchor_date
interval
day_of_month
month_of_year
weekday
nth_weekday
weekend_policy
start_date
end_date
created_at
```

Some fields will be null depending on recurrence type.

---

# 18. Supported Schedule Types

Required V0.1 schedule types:

```text
one_time
weekly
every_n_weeks
monthly
every_n_months
yearly
specific_dates
```

Potential later types:

```text
nth_weekday_of_month
last_weekday_of_month
business_day
```

---

# 19. Biweekly Payments

Biweekly recurrence should use a known anchor date.

Example:

```text
schedule_type = every_n_weeks
interval      = 2
anchor_date   = 2026-08-14
```

Expected:

```text
2026-08-14
2026-08-28
2026-09-11
2026-09-25
2026-10-09
...
```

Do not approximate:

```text
biweekly = twice monthly
```

This is incorrect.

Some months contain three biweekly occurrences.

Those months should naturally emerge from the scheduling engine.

---

# 20. Monthly Payments

Example:

```text
schedule_type = monthly
day_of_month  = 15
```

Generate one occurrence on the 15th of every applicable month.

---

# 21. Month-End Behavior

If something is scheduled for day 29, 30, or 31 and the target month does not contain that day:

Use the final calendar day of the month.

Example:

```text
Jan 31
Feb 28
Mar 31
Apr 30
```

Leap year:

```text
Feb 29
```

---

# 22. Annual Payments

Example:

```text
Vehicle registration

schedule_type = yearly
month_of_year = 11
day_of_month  = 17
```

Generate:

```text
Nov 17, 2026
Nov 17, 2027
Nov 17, 2028
...
```

---

# 23. Specific-Date Schedules

Some financial obligations may have arbitrary dates.

```text
schedule_dates
--------------
id
schedule_id
occurrence_date
```

Example:

```text
2026-09-12
2026-10-04
2027-01-15
```

---

# 24. Start and End Dates

All recurring schedules should optionally support:

```text
start_date
end_date
```

No occurrence may be generated outside the valid interval.

This matters for:

- Financing
- Temporary subscriptions
- Fixed-term loans
- Contract income
- Promotional payments

---

# 25. Weekend Policies

Architecture should support:

```text
exact
previous_business_day
next_business_day
```

V0.1 may implement only:

```text
exact
```

initially.

Do not make the schema incompatible with future business-day support.

Canadian statutory holiday handling is not required initially.

---

# 26. Debts

Debt should be a first-class domain object.

Suggested model:

```text
debts
-----
id
name
debt_type
current_balance
currency
interest_rate
minimum_payment
payment_schedule_id
payment_account_id
active
start_date
end_date
notes
```

Examples:

```text
student_loan
credit_card
vehicle_loan
personal_loan
line_of_credit
other
```

---

# 27. Debt Snapshots

```text
debt_snapshots
--------------
id
debt_id
balance
snapshot_date
created_at
```

This provides historical debt tracking.

---

# 28. Debt Calculations

Initial V0.1 does not require sophisticated amortization modeling.

Required:

- Store current balance
- Store interest rate
- Store minimum payment
- Store repayment schedule
- Track historical balance
- Include debt in net worth

Later:

- Interest projection
- Payoff dates
- Snowball
- Avalanche
- Additional-payment simulations

---

# 29. One-Time Events

Support arbitrary future income and expenses.

```text
one_time_events
---------------
id
name
event_date
amount
currency
category_id
account_id
event_type
notes
```

Example:

```text
Vacation
2026-10-15
expense
$2,000
```

or:

```text
Tax refund
2027-04-20
income
$1,800
```

These events participate directly in cash-flow forecasts.

---

# 30. Investment Accounts

Investment accounts are different from ordinary bank accounts.

Suggested model:

```text
investment_accounts
-------------------
id
name
account_type
institution
cash_balance
cash_currency
include_in_net_worth
active
created_at
updated_at
```

Initial account types:

```text
tfsa
fhsa
rrsp
non_registered
other
```

Initial expected use:

```text
TFSA
FHSA
```

---

# 31. Investment Holdings

```text
investment_holdings
-------------------
id
investment_account_id
symbol
name
asset_type
quantity
average_cost
cost_currency
quote_currency
active
created_at
updated_at
```

Examples:

```text
XEQT
AAPL
```

Possible asset types:

```text
etf
stock
mutual_fund
cash_equivalent
other
```

---

# 32. Holding Currency

Do not assume securities use the account's reporting currency.

Example:

```text
TFSA account reporting/base context: CAD

XEQT:
quote_currency = CAD

AAPL:
quote_currency = USD
```

A single investment account may therefore contain holdings quoted in multiple currencies.

---

# 33. Security Prices

```text
security_prices
---------------
id
symbol
price
currency
price_date
source
created_at
```

Sources:

```text
manual
api
import
```

V0.1 must support manual price updates.

Automatic market-data integration is optional.

Do not block application functionality on network availability.

---

# 34. Investment Valuation

For each holding:

```text
native_market_value =
quantity × latest_security_price
```

Then convert to reporting currency where necessary.

Example:

```text
AAPL

8 shares
USD $230/share

Native market value:
USD $1,840

USD/CAD rate:
1.37

Reporting market value:
CAD $2,520.80
```

Investment account value:

```text
cash
+ converted market value of all holdings
```

---

# 35. Investment Transactions

Prepare for:

```text
investment_transactions
-----------------------
id
investment_account_id
transaction_date
transaction_type
symbol
quantity
price
currency
amount
fees
notes
```

Possible types:

```text
contribution
withdrawal
buy
sell
dividend
interest
fee
transfer
```

Full portfolio accounting does not need to be implemented immediately.

Schema support should exist so the feature can be added without major redesign.

---

# 36. TFSA / FHSA Contribution Tracking

Treat contribution room separately from portfolio value.

Potential future fields/data:

```text
available_contribution_room
contributions_this_year
withdrawals_this_year
room_as_of_date
```

Do not infer contribution room solely from holdings.

Do not claim the application's value is an authoritative CRA number unless the user explicitly enters authoritative CRA information.

---

# 37. Investment Snapshots

```text
investment_snapshots
--------------------
id
investment_account_id
market_value
reporting_currency
cash_balance
snapshot_date
created_at
```

Snapshots support:

- Portfolio-value charts
- Net-worth charts
- TFSA growth
- FHSA growth

---

# 38. Cash-Flow Projection Engine

Given:

- Current cash balances
- Recurring income
- Recurring expenses
- Debt payments
- One-time events

generate a chronological cash-flow projection.

Example:

```text
Starting cash:                       $4,300

Aug 14   Salary           +$2,150    $6,450
Aug 15   Student Loan       -$420    $6,030
Aug 18   Internet            -$85    $5,945
Aug 21   Insurance          -$190    $5,755
Aug 28   Salary           +$2,150    $7,905
Aug 28   Car Payment        -$410    $7,495
Sep 01   Rent             -$1,600    $5,895
```

---

# 39. Projection Event Structure

The projection service should return structured records approximately like:

```text
date
description
amount
currency
reporting_amount
event_type
source_record_id
account_id
running_balance
```

Projection data should not be coupled directly to the table UI.

This same data should eventually feed graphs.

---

# 40. Projection Horizons

Support:

```text
7 days
30 days
60 days
90 days
6 months
12 months
custom range
```

Future events should generally be generated dynamically.

Do not create thousands of persisted occurrences for recurring schedules.

---

# 41. Same-Day Ordering

Use deterministic ordering.

Suggested:

1. Income
2. Transfers/adjustments
3. Required expenses
4. Debt payments
5. Other expenses

A future version may add user-controlled ordering.

---

# 42. Operating Cash

Investment value should not ordinarily participate in day-to-day cash-flow projections.

For example:

```text
Chequing   $4,000
Savings    $6,000
TFSA      $20,000
FHSA      $10,000
```

Operating cash might be:

```text
$10,000
```

not:

```text
$40,000
```

unless the user explicitly configures an account as available cash.

---

# 43. Committed Cash

The application should distinguish:

```text
bank balance
```

from:

```text
money already committed
```

Example:

```text
Chequing                $6,400

Upcoming:
Rent                    $1,600
Credit card             $1,100
Car                       $600
Insurance                 $300

Committed               $3,600
Unallocated             $2,800
```

The horizon should be configurable.

Examples:

```text
until next paycheque
next 30 days
next 60 days
```

---

# 44. Safe-to-Spend

Provide a derived metric:

```text
safe_to_spend =
minimum_projected_cash_balance
- configured_cash_reserve
```

Clamp display at zero if desired.

Example:

```text
Minimum projected cash:
$2,400

Desired reserve:
$1,500

Safe to spend:
$900
```

This is a model-generated value based on entered assumptions, not financial advice.

---

# 45. Net Worth

Implement a dedicated net-worth service.

Conceptually:

```text
net_worth =

cash
+ savings
+ investments
+ other included assets
- debts
- credit liabilities
```

All values should be converted into the configured reporting currency.

Default:

```text
CAD
```

---

# 46. Net Worth vs Available Cash

Never conflate:

```text
Net Worth
```

with:

```text
Safe to Spend
```

Example:

```text
Net worth:
-$35,000

Operating cash:
$7,500

Safe to spend:
$900
```

These answer completely different questions.

---

# 47. Dashboard

The dashboard should eventually provide approximately:

```text
Operating Cash               $X
Savings                      $X
Investments                  $X
Total Assets                 $X
Debt                         $X
Net Worth                    $X

Expected Income This Month   $X
Expected Outflow This Month  $X

Committed Cash               $X
Safe to Spend                $X

30-Day Minimum Cash          $X
60-Day Minimum Cash          $X
90-Day Minimum Cash          $X
```

Also display:

```text
Next paycheque
Next bill
Next major payment
```

---

# 48. Dashboard Upcoming Events

Example:

```text
UPCOMING
────────────────────────────────

Aug 14   Paycheque       +$2,150
Aug 15   Student Loan      -$420
Aug 18   Internet           -$85
Aug 21   Insurance         -$190
Aug 28   Paycheque       +$2,150
```

---

# 49. Update Finances Screen

Manual balance maintenance should be extremely fast.

Example:

```text
Update Finances
────────────────────────────────

Chequing

Previous:
$3,820 CAD

Current:
[ $3,644 ]


Savings

Previous:
$5,820 CAD

Current:
[ $6,120 ]


Visa

Previous:
$1,483 CAD

Current:
[ $1,102 ]


Student Loan

Previous:
$82,420 CAD

Current:
[ $81,980 ]


Snapshot Date:
[ 2026-08-12 ]

[ Save Updates ]
```

Saving should:

1. Update current values.
2. Create historical snapshots.
3. Refresh calculations.
4. Refresh dashboard.
5. Refresh relevant charts.

---

# 50. Investment Update Workflow

Provide a similarly efficient screen.

Example:

```text
Update Investments
────────────────────────────────

TFSA

XEQT
Units:      120.532
Price:      $XX.XX CAD

AAPL
Units:      8
Price:      $XXX.XX USD

Cash:
$420 CAD


FHSA

XEQT
Units:      75.24
Price:      $XX.XX CAD
```

Changing prices or quantities should automatically recalculate:

- Holding value
- Account value
- Total investments
- Net worth

---

# 51. Main Navigation

Preferred sidebar structure:

```text
Dashboard
Cash Flow

Accounts
Income
Recurring Expenses
Debts

Investments

Update Finances

Analytics

Settings
```

Within investments:

```text
Overview
TFSA
FHSA
Other Accounts
```

---

# 52. Qt GUI Requirements

The GUI should be treated as an important product requirement, not an afterthought.

Use PySide6 and create a polished native desktop application.

Desired characteristics:

- Clean sidebar navigation
- Modern spacing
- Consistent typography
- Clear visual hierarchy
- Summary cards
- Well-designed tables
- Inline controls
- Useful empty states
- Responsive resizing
- Dark-mode support
- Light-mode support if straightforward
- Proper Qt layouts rather than fixed pixel positioning

Avoid the appearance of a generic database-admin tool.

---

# 53. UI Components

Build reusable components for:

```text
MetricCard
MoneyLabel
SectionHeader
DataTable
DateRangeSelector
AccountSelector
CurrencyLabel
EmptyState
ChartContainer
FormDialog
ConfirmationDialog
```

Avoid duplicating formatting logic throughout screens.

---

# 54. Monetary Formatting

Centralize monetary formatting.

Examples:

```text
$1,234.56 CAD
US$1,234.56
-$820.00
```

Display may optionally omit currency codes when the context is unambiguous.

Internally, always retain explicit currency information.

Do not use floating-point binary arithmetic for stored money.

Use:

- Decimal
- Integer minor units

as appropriate.

Financial calculations should avoid float rounding errors.

---

# 55. Visualization Architecture

Charts are a planned feature and should influence architecture from the beginning.

Calculation services should return generic structured datasets that can feed either:

- Tables
- Dashboard cards
- Charts
- Reports

Example:

```python
[
    {
        "date": ...,
        "cash": ...,
        "debt": ...,
        "investments": ...,
        "net_worth": ...
    }
]
```

Do not put financial calculations inside graph widgets.

---

# 56. Charting Library

Potential options:

```text
PyQtGraph
QtCharts / QCharts
Matplotlib embedded in Qt
```

Choose whichever provides the best balance of:

- Native Qt integration
- Maintainability
- Good appearance
- Interactivity
- Performance

Keep chart-specific code behind an abstraction where reasonable.

---

# 57. Planned Chart: Net Worth Over Time

Primary long-term chart.

Show:

```text
date → net worth
```

Potential accompanying series:

```text
cash
investments
debt
net worth
```

This should allow the user to see financial progress independent of daily spending noise.

---

# 58. Planned Chart: Cash-Flow Forecast

This is one of the most useful planned charts.

Plot:

```text
date → projected operating cash
```

The line should naturally produce a sawtooth shape:

```text
paycheque ↑
bills     ↓
paycheque ↑
bills     ↓
```

Use the exact same projection events as the cash-flow table.

Do not implement a separate approximate chart model.

---

# 59. Planned Chart: Debt Reduction

Display:

```text
date → debt balance
```

Potential modes:

```text
Total debt
Student debt
Vehicle debt
Credit card debt
Individual debt selection
```

---

# 60. Planned Chart: Investment Value

Display:

```text
date → investment value
```

Potential series:

```text
TFSA
FHSA
Total investments
```

---

# 61. Planned Chart: Portfolio Allocation

Potential views:

```text
By security

XEQT       82%
AAPL       12%
Cash        6%
```

or:

```text
By account

TFSA
FHSA
Other
```

---

# 62. Planned Chart: Income vs Spending

Monthly:

```text
Month       Income       Spending
Jan
Feb
Mar
...
```

This should eventually support identifying periods of unusually high outflow.

---

# 63. Planned Chart: Spending Categories

Once transaction tracking exists:

```text
Housing
Food
Restaurants
Transportation
Subscriptions
Entertainment
etc.
```

Avoid making pie charts the foundation of the product.

Historical trends and cash-flow charts are more valuable.

---

# 64. Historical State Principle

Never overwrite data that is useful for historical analysis.

Maintain dated observations for:

- Account balances
- Debt balances
- Investment valuations
- Security prices
- Exchange rates

This allows future analytics without reconstructing history.

---

# 65. Analytics Service

Create a dedicated analytics layer.

Do not have the dashboard independently calculate financial metrics.

Potential methods:

```text
get_current_net_worth()
get_net_worth_history()
get_total_debt()
get_debt_history()
get_investment_value()
get_cash_position()
get_monthly_income()
get_monthly_outflow()
get_safe_to_spend()
get_lowest_projected_balance()
get_upcoming_events()
```

---

# 66. Monthly Normalization

For comparison only, recurring values may be normalized.

Examples:

Weekly:

```text
amount × 52 / 12
```

Biweekly:

```text
amount × 26 / 12
```

Annual:

```text
amount / 12
```

These values are useful for:

- Spending analysis
- Category comparisons
- Annualized totals

They must not replace actual scheduled events in projections.

---

# 67. Three-Paycheque / Three-Payment Months

The scheduling and analytics services should make it possible to identify:

```text
months with 3 biweekly paycheques
```

and:

```text
months with 3 biweekly expenses
```

These may later be highlighted on the dashboard or calendar.

---

# 68. Recurring Payment Management

Provide a table:

```text
Name        Amount    Schedule          Next Date    Priority
Rent        $1,600    Monthly, 1st      Sep 1        Essential
Car         $410      Every 2 weeks     Aug 28       Important
Spotify     $12       Monthly, 14th     Aug 14       Luxury
Insurance   $190      Monthly, 21st     Aug 21       Essential
```

Operations:

- Add
- Edit
- Disable
- Delete

Prefer disabling records when historical context may matter.

---

# 69. Cash-Flow Screen

Display chronological projection.

Columns:

```text
Date
Description
Type
Category
Amount
Currency
Converted Amount
Projected Balance
```

Provide horizon controls:

```text
7D
30D
60D
90D
6M
1Y
Custom
```

---

# 70. Settings

Suggested application settings:

```text
reporting_currency
default_projection_days
cash_reserve_amount
date_format
theme
database_path
automatic_market_prices
automatic_fx_rates
```

Defaults:

```text
reporting_currency = CAD
theme              = dark/system
```

---

# 71. Optional Automatic FX Rates

If straightforward, implement automatic currency-rate lookup.

Requirements:

- Treat it as optional.
- Cache retrieved rates in `exchange_rates`.
- Never require internet access.
- Fall back to latest cached/manual rate.
- Show rate date/source somewhere accessible.
- Allow manual override.
- Do not silently replace historical manually entered rates.

Architecture example:

```text
CurrencyService

get_rate(
    from_currency,
    to_currency,
    date
)

priority:

1. Exact cached historical rate
2. External lookup if enabled
3. Latest cached rate
4. Manual rate
5. Clear "rate unavailable" state
```

This is a convenience feature, not critical infrastructure.

---

# 72. Optional Automatic Market Prices

Market-price retrieval should follow similar principles.

Priority:

```text
1. Cached current price
2. External lookup if enabled
3. Latest stored price
4. Manual entry
```

Store every retrieved observation in `security_prices`.

Never discard the native currency.

---

# 73. Privacy

All core financial information remains local.

Do not implement telemetry.

Do not send:

- Balances
- Debt information
- Spending
- Income
- Holdings
- Account information

to external services.

If optional market/FX APIs are eventually enabled, requests should contain only the minimum information necessary, such as:

```text
AAPL
USD/CAD
```

not the user's holdings or balances.

---

# 74. Database Location

Use an appropriate Linux application-data directory.

For example:

```text
~/.local/share/personal-finance-tracker/
```

Suggested database:

```text
finance.db
```

---

# 75. Backup

Provide an easy local database backup.

At minimum:

```text
Settings
→ Backup Database
```

Output:

```text
finance-backup-YYYY-MM-DD.db
```

A future version may support automatic rotating local backups.

---

# 76. Export

Potential CSV exports:

```text
Accounts
Balance snapshots
Debts
Debt snapshots
Recurring expenses
Income
Investment holdings
Investment transactions
```

Not all exports are required for first implementation.

---

# 77. Transactions — Future Feature

Prepare schema for ordinary spending transactions.

```text
transactions
------------
id
account_id
transaction_date
description
amount
currency
category_id
source
external_id
notes
```

Sources:

```text
manual
csv_import
ofx_import
qfx_import
```

Do not make individual transaction entry mandatory for the app to be useful.

---

# 78. CSV Import — Future Feature

A high-value future feature is transaction import from bank/credit-card CSV exports.

Potential workflow:

```text
Import CSV
↓
Select account
↓
Map columns
↓
Preview
↓
Import
↓
Categorize
```

Remember mappings per financial institution where possible.

---

# 79. Duplicate Detection

Future transaction import should support duplicate prevention.

Potential keys:

```text
account
date
amount
description
external_id
```

Prefer explicit external IDs where available.

---

# 80. Scenario Lab — Future Feature

Allow hypothetical changes without changing real financial records.

Example:

```text
Scenario:
"Cut some bullshit"

Remove:
Subscription A       +$20/month
Subscription B       +$15/month

Reduce:
Restaurants          +$150/month

Keep:
Important luxury      unchanged

Increase:
Debt repayment       -$400/month
```

Return:

```text
Monthly difference
Annual difference
Cash-flow difference
Debt impact
```

---

# 81. Scenario Lab Examples

Support questions such as:

```text
Can I afford a $2,000 vacation in October?

What happens if rent rises $300?

What happens if I put another $500/month toward student debt?

What if income stops for three months?

What if I buy something for $1,500 today?
```

These should reuse the existing cash-flow engine wherever possible.

---

# 82. Debt Payoff Simulator — Future Feature

Strategies:

```text
Minimum Payments
Avalanche
Snowball
Custom
```

Potential outputs:

```text
Estimated payoff date
Total projected interest
Interest saved
Months saved
```

---

# 83. Spending Insights — Future Feature

Once enough historical data exists, produce useful observations.

Examples:

```text
Dining spending has increased 18% over the last three months.

Your five lowest-priority recurring expenses total $97/month.

September has $820 more scheduled outflow than your six-month average.

Your next three-paycheque month is January.

Your debt decreased by $X over the last six months.

Your net worth improved by $Y over the last year.
```

Avoid nagging language.

Present facts.

---

# 84. Registered Account Insights — Future Feature

Potential future TFSA/FHSA information:

```text
Current account value
Contributions this year
Current user-entered contribution room
Portfolio allocation
Unrealized gain/loss
Dividends
```

Contribution-room logic should remain clearly separate from portfolio performance.

---

# 85. V0.1 Required Screens

Implement:

1. Dashboard
2. Cash Flow
3. Accounts
4. Income
5. Recurring Expenses
6. Debts
7. Investments
8. Update Finances
9. Settings

A minimal Analytics page may also be created if initial charts are implemented.

---

# 86. V0.1 Investment Screen

At minimum:

```text
Investments
────────────────────────────────

Total Investments         $XX,XXX CAD

TFSA                      $XX,XXX CAD
FHSA                      $XX,XXX CAD
```

Selecting an account:

```text
TFSA
──────────────────────────────────────────

Symbol   Units     Price         Value CAD
XEQT     125.42    $XX.XX CAD    $XX,XXX
AAPL       8.00    $XXX.XX USD   $X,XXX
Cash                              $XXX

Total                            $XX,XXX
```

---

# 87. V0.1 Acceptance Criteria

The initial application is successful when the user can:

1. Launch the app locally on Linux.
2. Create bank/cash accounts.
3. Enter balances.
4. Create debts.
5. Enter debt balances.
6. Create recurring income.
7. Create recurring expenses.
8. Configure exact recurrence schedules.
9. Correctly represent biweekly schedules.
10. Add annual expenses.
11. Add one-time expenses/income.
12. Generate chronological cash-flow projections.
13. See projected running balances.
14. See lowest projected balance over 30/60/90 days.
15. See committed cash.
16. See safe-to-spend cash.
17. Update balances quickly.
18. Preserve historical snapshots.
19. Create TFSA/FHSA accounts.
20. Add ETF/stock holdings.
21. Enter holding quantities.
22. Enter security prices.
23. Support CAD and USD holdings.
24. Convert foreign assets into CAD reporting values.
25. Calculate investment account values.
26. Calculate total investment value.
27. Include investments in net worth.
28. Exclude investments from operating cash.
29. Preserve investment snapshots.
30. Close/reopen without data loss.
31. Back up the SQLite database.

---

# 88. Scheduling Tests

The scheduling service must have automated unit tests independent of the GUI.

## Biweekly

Anchor:

```text
2026-08-14
```

Expected:

```text
2026-08-14
2026-08-28
2026-09-11
2026-09-25
2026-10-09
```

---

# 89. Monthly Tests

Schedule:

```text
day_of_month = 15
```

Expected:

One event on the 15th of each month.

---

# 90. Month-End Tests

Schedule:

```text
day_of_month = 31
```

Expected:

```text
Jan 31
Feb 28/29
Mar 31
Apr 30
```

---

# 91. Annual Tests

Schedule:

```text
month = 11
day   = 17
```

Expected:

November 17 each year.

---

# 92. Boundary Tests

Verify:

```text
no event before start_date
no event after end_date
```

---

# 93. Projection Tests

Create deterministic tests using known starting values.

Example:

```text
Starting cash:
$1,000

Aug 14:
+$2,000 salary

Aug 15:
-$500 bill
```

Expected:

```text
Aug 14:
$3,000

Aug 15:
$2,500
```

---

# 94. Currency Tests

Required tests:

```text
CAD → CAD
```

must return the original value.

Known USD/CAD rate:

```text
1 USD = 1.40 CAD
```

Then:

```text
100 USD → 140 CAD
```

Verify that original native values remain unchanged.

---

# 95. Investment Tests

Example:

```text
AAPL

quantity = 10
price = 200 USD
USD/CAD = 1.40
```

Expected:

```text
native value = 2,000 USD
reporting value = 2,800 CAD
```

---

# 96. Net-Worth Tests

Example:

```text
Cash          10,000 CAD
TFSA          20,000 CAD
FHSA          10,000 CAD
Debt          70,000 CAD
```

Expected:

```text
Net worth = -30,000 CAD
```

Operating cash:

```text
10,000 CAD
```

not:

```text
40,000 CAD
```

---

# 97. Data Precision

Use proper decimal handling.

Do not rely on Python binary `float` for financial amounts.

Preferred:

```python
Decimal
```

or integer minor units where appropriate.

Investment quantities may require more precision than two decimal places.

Examples:

```text
125.423817 ETF units
```

Prices and quantities should therefore use configurable decimal precision.

---

# 98. Database Migrations

Use migrations from the beginning.

Even though this is a personal application, the schema will evolve.

Do not require deleting/recreating the database whenever a model changes.

---

# 99. Error Handling

The UI should show readable errors.

Examples:

```text
Exchange rate unavailable.

Unable to calculate AAPL value because no USD/CAD rate exists.

No price has been entered for XEQT.

Projection cannot include an expense with no valid schedule.
```

Do not fail silently.

---

# 100. Empty States

Provide meaningful empty states.

Example:

```text
No debts added yet.

[ Add Debt ]
```

rather than displaying an empty table without explanation.

---

# 101. Performance Expectations

Data volume will be small.

Optimize for:

- Correctness
- Maintainability
- Responsive UI

rather than premature scale.

Even years of personal transactions should be trivial for SQLite.

---

# 102. Development Priorities

Implement in this order.

## Phase 1 — Foundation

- Project structure
- SQLite
- SQLAlchemy
- Migrations
- Core models
- Settings
- Decimal money utilities

## Phase 2 — Scheduling

- Schedule model
- Recurrence generation
- Start/end dates
- Monthly behavior
- Biweekly behavior
- Tests

## Phase 3 — Cash Flow

- Income
- Recurring expenses
- One-time events
- Projection engine
- Running balances
- Tests

## Phase 4 — Balance Sheet

- Accounts
- Debts
- Balance snapshots
- Debt snapshots
- Net worth

## Phase 5 — Investments

- Investment accounts
- Holdings
- Prices
- Valuation
- TFSA
- FHSA
- Investment snapshots

## Phase 6 — Currency

- Currency model
- Exchange rates
- Conversion service
- CAD reporting
- USD holdings

Currency support may be implemented alongside investments if more convenient.

## Phase 7 — Qt UI

- Main shell/sidebar
- Dashboard
- CRUD screens
- Cash-flow screen
- Investments
- Update Finances

## Phase 8 — Polish

- Consistent styling
- Dark theme
- Formatting
- Empty states
- Validation
- Backup

## Phase 9 — Visualization

- Cash-flow forecast chart
- Net-worth chart
- Debt chart
- Investment chart

## Phase 10 — Future Automation

- CSV import
- Market-price lookup
- FX lookup
- Analytics
- Scenario Lab

---

# 103. Initial Visualization Recommendation

If adding one chart during V0.1 is straightforward, prioritize:

## Projected Cash Balance

```text
X axis:
date

Y axis:
operating cash
```

This chart directly visualizes the core value of the application.

Second priority:

## Net Worth Over Time

These two charts answer:

```text
Can I afford things right now?

Am I becoming financially healthier over time?
```

---

# 104. Do Not Overbuild V0.1

Avoid implementing prematurely:

- Bank APIs
- Brokerage authentication
- Cloud synchronization
- AI insights
- Tax calculations
- Detailed portfolio performance accounting
- Full CRA TFSA/FHSA rules
- Complex loan amortization
- Double-entry accounting
- Multi-user support
- Mobile support

Architect cleanly for future features without delaying a usable application.

---

# 105. Final Architectural Rules

The implementation should follow these rules.

### Rule 1

Actual dated events are authoritative for cash flow.

### Rule 2

Monthly equivalents are derived analytics.

### Rule 3

Current balances and historical snapshots are separate.

### Rule 4

Cash and investments are separate.

### Rule 5

Net worth and spendable cash are separate.

### Rule 6

Holding, quantity, price, currency, and valuation are separate concepts.

### Rule 7

Native-currency values must be preserved.

### Rule 8

Currency conversion occurs in a centralized service.

### Rule 9

Financial calculations must be independent of Qt widgets.

### Rule 10

Charts consume the same datasets as tables and dashboard metrics.

### Rule 11

Manual entry must always remain possible even when automation exists.

### Rule 12

No essential functionality should require an internet connection.

---

# 106. Intended End State

The finished application should eventually feel like a private financial cockpit:

```text
                  PERSONAL FINANCES

     CASH FLOW           BALANCE SHEET
     ─────────           ─────────────

     Cash                Cash
     Income              Savings
     Bills               TFSA
     Debt Payments       FHSA
     Upcoming Costs      Other Assets
                         Debt
           │                 │
           └────────┬────────┘
                    │
                    ▼

                NET WORTH
                    │
                    ▼

                 HISTORY
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼

       Charts    Insights   Scenarios
```

The central purpose remains simple:

> **Know what money exists, where it is going, what is already committed, what is invested, what is owed, and whether the overall trajectory is improving.**