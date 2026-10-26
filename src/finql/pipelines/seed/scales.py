from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Scale:
    name: str
    customers: int
    transactions: int  # target; the generator calibrates activity to land close to it
    months: int  # length of the transaction history
    branches: int
    merchants: int
    # The last full month of the history. Fixed (not "last month"), so the same seed gives the
    # same data whenever it runs, and the eval's expected answers stay valid.
    end_month: date = date(2026, 9, 1)

    @property
    def period_start(self) -> date:
        year, month = divmod(self.end_month.year * 12 + self.end_month.month - self.months, 12)
        return date(year, month + 1, 1)

    @property
    def business_date(self) -> date:
        """The bank's "today": the last day of the last month."""
        year, month = divmod(self.end_month.year * 12 + self.end_month.month, 12)
        return date(year, month + 1, 1) - timedelta(days=1)


SCALES = {
    # 15 months: enough for "last September" and quarter-over-quarter questions in the tests.
    "tiny": Scale("tiny", customers=200, transactions=30_000, months=15, branches=6, merchants=150),
    "small": Scale(
        "small", customers=10_000, transactions=2_000_000, months=24, branches=20, merchants=600
    ),
    "large": Scale(
        "large", customers=50_000, transactions=15_000_000, months=36, branches=20, merchants=1500
    ),
}
