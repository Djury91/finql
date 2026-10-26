"""Synthetic bank data: realistic distributions plus planted, verifiable "stories".

The stories give the eval questions a known right answer:

1. Card spending at the Debrecen branch (DEB01) grows 40% in the last quarter of the period,
   so it tops any quarter-over-quarter comparison.
2. A campaign in March 2025 more than doubles the number of new accounts that month.
3. Card spending peaks in December, and Friday/Saturday beat the rest of the week.
4. About 4% of the active loans are past due; personal loans default more than mortgages,
   and a high risk rating triples the chance.
5. Premium customers spend more, with restaurants, hotels and travel over-represented.

Everything comes from seeded `random.Random` instances (and a seeded Faker), so a given scale
and seed always produces the same rows. Each lazily generated stream (customers, cards,
transactions) has its own generator, so the output does not depend on which stream was read
first. Rows are plain tuples in the table's COPY column order.
"""

import bisect
import math
import random
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import accumulate

from faker import Faker

from finql.pipelines.seed import identifiers
from finql.pipelines.seed.reference import (
    BRANCHES,
    CAMPAIGN_FACTOR,
    CAMPAIGN_MONTH,
    CATEGORY_TILT,
    FOREIGN_CITIES,
    FX_START,
    GROWTH_STORY_BRANCH,
    GROWTH_STORY_FACTOR,
    HOLIDAY_FACTOR,
    MERCHANT_CATEGORIES,
    MONTH_FACTOR,
    PRODUCT_IDS,
    PRODUCTS,
    PRODUCTS_BY_KEY,
    REGION_COUNTY_CODE,
    REGION_TOWNS,
    WEEKDAY_FACTOR,
    Branch,
    hungarian_holidays,
)
from finql.pipelines.seed.scales import Scale

Row = tuple[object, ...]
# Positions in a transaction row (the COPY column order, see loader.TRANSACTION_COLUMNS).
COL_AMOUNT, COL_CHANNEL = 5, 7

HISTORY_START = date(2008, 1, 1)  # the oldest customer relationship
CARD_VALIDITY_MONTHS = 48
ANNUAL_PRICE_GROWTH = 0.045  # amounts drift up with inflation

# Products a customer holds besides the main current account: (product, probability).
INDIVIDUAL_PRODUCTS = {
    "retail": (
        ("savings", 0.55),
        ("credit_card", 0.40),
        ("retail_eur", 0.12),
        ("personal_loan", 0.14),
        ("mortgage", 0.09),
    ),
    "premium": (
        ("savings", 0.80),
        ("credit_card", 0.70),
        ("retail_eur", 0.45),
        ("personal_loan", 0.10),
        ("mortgage", 0.15),
    ),
}
COMPANY_PRODUCTS = (
    ("business_eur", 0.45),
    ("business_usd", 0.10),
    ("business_deposit", 0.40),
    ("business_card", 0.30),
    ("business_loan", 0.30),
)

# Past-due loans: base probability by product, multiplier by risk rating, DPD bucket shares.
DELINQUENCY_RATE = {"personal_loan": 0.075, "mortgage": 0.025, "business_loan": 0.05}
RISK_MULTIPLIER = {"low": 0.6, "medium": 1.3, "high": 3.0}
DPD_BUCKETS = ((1, 30, 0.45), (31, 60, 0.20), (61, 90, 0.12), (91, 400, 0.23))

# Variable events per account profile, relative to the calibrated activity level.
VARIABLE_RATES: dict[str, dict[str, float]] = {
    "personal_current": {"card": 1.0, "atm": 0.12, "transfer_out": 0.10, "transfer_in": 0.04},
    "personal_fx": {"card": 0.15, "transfer_in": 0.03},
    "credit_card": {"card": 0.6},
    "savings": {"transfer_out": 0.03},
    "business_current": {"card": 0.3, "transfer_in": 0.8, "transfer_out": 0.6},
    "business_fx": {"transfer_in": 0.15, "transfer_out": 0.12},
    "loan": {},
}
SEGMENT_CARD_FACTOR = {"retail": 1.0, "premium": 1.4, "sme": 1.0, "corporate": 1.6}
SEGMENT_AMOUNT_FACTOR = {"retail": 1.0, "premium": 1.9, "sme": 1.5, "corporate": 3.0}

MONTHLY_FEE = {
    "retail_current": 1990,
    "premium_current": 9900,
    "retail_eur": 2,
    "business_current": 6900,
    "business_eur": 10,
    "business_usd": 10,
}
DIRECT_DEBITS = (
    ("Áramszolgáltatás – csoportos beszedés", 9000, False),
    ("Gázszolgáltatás – csoportos beszedés", 11000, True),  # winter peak
    ("Telefon és internet – csoportos beszedés", 8500, False),
    ("Biztosítás – csoportos beszedés", 6000, False),
)
FOREIGN_WORDS = {
    "grocery": "Supermarkt",
    "restaurant": "Ristorante",
    "clothing": "Fashion",
    "hotel": "Hotel",
    "travel": "Travel",
}
CATEGORIES_BY_CODE = {c.code: c for c in MERCHANT_CATEGORIES}
# Card purchases by hour of day, 07:00 … 22:59.
CARD_HOUR_CUM = list(accumulate((1, 2, 3, 3, 3, 4, 4, 3, 3, 4, 5, 5, 4, 3, 2, 1)))
ATM_AMOUNTS = (5000, 10000, 20000, 30000, 50000, 100000)
ATM_WEIGHTS = (0.10, 0.25, 0.30, 0.15, 0.15, 0.05)


@dataclass
class Customer:
    customer_id: int
    kind: str  # 'individual' | 'company'
    segment: str
    branch: Branch
    branch_id: int
    risk: str
    created: date
    birth_date: date | None


@dataclass
class Card:
    card_id: int
    issued: date
    expires: date


@dataclass
class Account:
    account_id: int
    customer: Customer
    product_key: str
    opened: date
    closed: date | None = None
    status: str = "active"
    credit_limit: int | None = None
    cards: list[Card] = field(default_factory=list)
    # Per-account behaviour, drawn once.
    income: float = 0.0  # salary, pension or payroll per month
    income_label: str = ""
    direct_debits: list[tuple[str, float, bool, int]] = field(default_factory=list)
    saves_monthly: bool = False

    @property
    def currency(self) -> str:
        return PRODUCTS_BY_KEY[self.product_key].currency

    @property
    def profile(self) -> str:
        product_type = PRODUCTS_BY_KEY[self.product_key].product_type
        business = self.customer.kind == "company"
        if product_type == "current_account":
            prefix = "business" if business else "personal"
            return f"{prefix}_current" if self.currency == "HUF" else f"{prefix}_fx"
        if product_type in ("savings", "credit_card"):
            return product_type
        return "loan"

    def card_on(self, day: date) -> int | None:
        for card in self.cards:
            if card.issued <= day < card.expires:
                return card.card_id
        return None


def add_months(day: date, months: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    return date(year, month + 1, min(day.day, 28))


def month_starts(first: date, last: date) -> list[date]:
    months = []
    current = first.replace(day=1)
    while current <= last:
        months.append(current)
        current = add_months(current, 1)
    return months


def month_end(month: date) -> date:
    return add_months(month, 1) - timedelta(days=1)


class SeedGenerator:
    def __init__(self, scale: Scale, seed: int = 42) -> None:
        self.scale = scale
        self.seed = seed
        self.rng = random.Random(seed)  # building the population (eager)
        self.tx_rng = self._stream_rng("transactions")
        self.faker = Faker("hu_HU")
        self.faker.seed_instance(seed)
        self.start = scale.period_start
        self.end = scale.business_date
        self.months = month_starts(self.start, self.end)
        self.story_months = frozenset(self.months[-3:]) if len(self.months) >= 6 else frozenset()
        self.branches = BRANCHES[: scale.branches]
        self._holidays = frozenset().union(
            *(hungarian_holidays(y) for y in range(self.start.year, self.end.year + 1))
        )
        self._card_seq = 0
        self._category_cache: dict[str, tuple[list[str], list[float]]] = {}
        self.customers: list[Customer] = []
        self.accounts: list[Account] = []
        self.fx: dict[tuple[date, str], float] = {}
        self._merchant_rows: list[Row] = []
        self._loan_rows: list[Row] = []
        self._installment_rows: list[Row] = []
        self._build()

    def _stream_rng(self, stream: str) -> random.Random:
        return random.Random(f"{self.seed}:{stream}")

    # --- reference tables -------------------------------------------------------------

    def branch_rows(self) -> list[Row]:
        return [(i, b.code, b.name, b.city, b.region) for i, b in enumerate(self.branches, start=1)]

    def product_rows(self) -> list[Row]:
        return [
            (i, p.product_type, p.name, p.currency, f"{p.interest_rate:.4f}")
            for i, p in enumerate(PRODUCTS, start=1)
        ]

    def merchant_rows(self) -> list[Row]:
        return self._merchant_rows

    def fx_rows(self) -> list[Row]:
        return [(day, currency, f"{rate:.4f}") for (day, currency), rate in sorted(self.fx.items())]

    def business_date(self) -> date:
        return self.end

    # --- customer side ---------------------------------------------------------------

    def customer_rows(self) -> Iterator[Row]:
        rng = self._stream_rng("customers")
        self.faker.seed_instance(f"{self.seed}:customers")
        used_tax_ids: set[str] = set()
        for c in self.customers:
            if c.kind == "individual":
                assert c.birth_date is not None
                name = self.faker.name()
                tax_id = identifiers.personal_tax_id(c.birth_date, rng)
                while tax_id in used_tax_ids:
                    tax_id = identifiers.personal_tax_id(c.birth_date, rng)
            else:
                name = self.faker.company()
                county = REGION_COUNTY_CODE[c.branch.region]
                tax_id = identifiers.company_tax_number(rng, county)
                while tax_id in used_tax_ids:
                    tax_id = identifiers.company_tax_number(rng, county)
            used_tax_ids.add(tax_id)
            city = (
                c.branch.city if rng.random() < 0.75 else rng.choice(REGION_TOWNS[c.branch.region])
            )
            yield (
                c.customer_id,
                c.kind,
                name,
                c.birth_date,
                tax_id,
                city,
                c.segment,
                c.branch_id,
                c.risk,
                f"{c.created} {rng.randrange(8, 18):02d}:{rng.randrange(60):02d}:00",
            )

    def account_rows(self) -> Iterator[Row]:
        for a in self.accounts:
            yield (
                a.account_id,
                a.customer.customer_id,
                PRODUCT_IDS[a.product_key],
                a.customer.branch_id,
                identifiers.iban(a.customer.branch_id, a.account_id),
                a.currency,
                a.status,
                a.opened,
                a.closed,
                a.credit_limit,
            )

    def card_rows(self) -> Iterator[Row]:
        rng = self._stream_rng("cards")
        for a in self.accounts:
            card_type = "credit" if a.profile == "credit_card" else "debit"
            for i, card in enumerate(a.cards):
                last = i == len(a.cards) - 1
                if card.expires <= self.end:
                    status = "expired"
                elif a.closed is not None or (last and rng.random() < 0.02):
                    status = "blocked"
                else:
                    status = "active"
                yield (
                    card.card_id,
                    a.account_id,
                    card_type,
                    status,
                    card.issued,
                    card.expires,
                    f"{rng.randrange(10000):04d}",
                )

    def loan_rows(self) -> list[Row]:
        return self._loan_rows

    def installment_rows(self) -> list[Row]:
        return self._installment_rows

    # --- building the population ------------------------------------------------------

    def _build(self) -> None:
        self._build_fx()
        self._build_merchants()
        self._build_customers()
        self._build_accounts()
        self._build_loans()

    def _build_fx(self) -> None:
        rates = dict(FX_START)
        day = self.start
        while day <= self.end:
            if day.weekday() < 5 and day not in self._holidays:  # MNB publishes on workdays
                for currency in rates:
                    rates[currency] *= math.exp(self.rng.gauss(0.0, 0.0025))
            for currency, rate in rates.items():
                self.fx[(day, currency)] = rate
            day += timedelta(days=1)

    def _build_merchants(self) -> None:
        total_weight = sum(c.weight for c in MERCHANT_CATEGORIES)
        merchant_id = 0
        self._merchants_by_category: dict[str, tuple[list[int], list[float]]] = {}
        self._foreign_by_category: dict[str, tuple[list[int], list[float]]] = {}
        branch_cities = [b.city for b in self.branches]
        branch_weights = [b.weight for b in self.branches]
        for category in MERCHANT_CATEGORIES:
            count = max(3, round(self.scale.merchants * category.weight / total_weight))
            foreign_count = max(2, count // 5) if category.foreign else 0
            local: list[int] = []
            foreign: list[int] = []
            for i in range(count + foreign_count):
                merchant_id += 1
                if i < count:
                    city = self.rng.choices(branch_cities, branch_weights)[0]
                    word = self.rng.choice(category.words)
                    suffix = self.rng.choice((" Kft.", " Kft.", " Bt.", ""))
                    name = f"{self.faker.last_name()} {word}{suffix}"
                    self._merchant_rows.append(
                        (merchant_id, name, category.mcc, category.code, city, "HU")
                    )
                    local.append(merchant_id)
                else:
                    country, city = self.rng.choice(FOREIGN_CITIES)
                    name = f"{FOREIGN_WORDS[category.code]} {city} {self.faker.last_name()}"
                    self._merchant_rows.append(
                        (merchant_id, name, category.mcc, category.code, city, country)
                    )
                    foreign.append(merchant_id)
            # Zipf-like popularity, so there are clear "top merchants".
            self._merchants_by_category[category.code] = (
                local,
                list(accumulate(1 / (rank**0.8) for rank in range(1, len(local) + 1))),
            )
            if foreign:
                self._foreign_by_category[category.code] = (
                    foreign,
                    list(accumulate(1 / (rank**0.8) for rank in range(1, len(foreign) + 1))),
                )

    def _random_date(self, low: date, high: date) -> date:
        """Uniform date in [low, high], with the campaign month over-weighted."""
        span = (high - low).days
        while True:
            day = low + timedelta(days=self.rng.randint(0, max(span, 0)))
            if day.replace(day=1) == CAMPAIGN_MONTH or self.rng.random() < 1 / CAMPAIGN_FACTOR:
                return day

    def _build_customers(self) -> None:
        branch_weights = [b.weight for b in self.branches]
        new_share = min(0.4, len(self.months) * 0.0125)
        for customer_id in range(1, self.scale.customers + 1):
            branch_index = self.rng.choices(range(len(self.branches)), branch_weights)[0]
            roll = self.rng.random()
            if roll < 0.10:
                kind, segment = "company", "sme"
            elif roll < 0.12:
                kind, segment = "company", "corporate"
            else:
                kind = "individual"
                segment = "premium" if self.rng.random() < 0.12 else "retail"
            risk_weights = (0.70, 0.22, 0.08) if kind == "individual" else (0.55, 0.33, 0.12)
            risk = self.rng.choices(("low", "medium", "high"), risk_weights)[0]
            if self.rng.random() < new_share:
                created = self._random_date(self.start, self.end - timedelta(days=7))
            else:
                created = self._random_date(HISTORY_START, self.start - timedelta(days=1))
            birth_date = None
            if kind == "individual":
                age_days = int(self.rng.triangular(18.1, 88, 42) * 365.25)
                birth_date = self.end - timedelta(days=age_days)
                # Nobody opens an account before turning 18.
                created = max(created, birth_date + timedelta(days=int(18 * 365.25) + 1))
                created = min(created, self.end - timedelta(days=7))
            self.customers.append(
                Customer(
                    customer_id,
                    kind,
                    segment,
                    self.branches[branch_index],
                    branch_index + 1,
                    risk,
                    created,
                    birth_date,
                )
            )

    def _build_accounts(self) -> None:
        for c in self.customers:
            if c.kind == "individual":
                main = "premium_current" if c.segment == "premium" else "retail_current"
                extras = INDIVIDUAL_PRODUCTS[c.segment]
            else:
                main, extras = "business_current", COMPANY_PRODUCTS
            self._open_account(c, main, c.created)
            for product_key, probability in extras:
                if self.rng.random() < probability:
                    product_type = PRODUCTS_BY_KEY[product_key].product_type
                    latest = self.end - timedelta(days=20)
                    earliest = c.created
                    if product_type in ("personal_loan", "business_loan"):
                        earliest = max(earliest, latest - timedelta(days=7 * 365))
                    self._open_account(c, product_key, self._random_date(earliest, latest))

    def _open_account(self, customer: Customer, product_key: str, opened: date) -> None:
        account = Account(len(self.accounts) + 1, customer, product_key, opened)
        profile = account.profile
        age = (
            (self.end - customer.birth_date).days / 365.25
            if customer.birth_date is not None
            else 0.0
        )
        amount_factor = SEGMENT_AMOUNT_FACTOR[customer.segment]

        if profile != "loan" and self.rng.random() < 0.04:
            low, high = opened + timedelta(days=60), self.end - timedelta(days=1)
            if low < high:
                account.closed = low + timedelta(days=self.rng.randint(0, (high - low).days))
                account.status = "closed"
        if account.status == "active" and profile != "loan" and self.rng.random() < 0.01:
            account.status = "frozen"

        if profile == "personal_current":
            if age >= 65:
                account.income = self.rng.uniform(170_000, 360_000)
                account.income_label = "Nyugdíj"
            elif self.rng.random() < 0.88:
                account.income = self.rng.lognormvariate(math.log(430_000 * amount_factor), 0.35)
                account.income_label = "Munkabér"
            for label, median, seasonal in DIRECT_DEBITS:
                if self.rng.random() < 0.55:
                    amount = self.rng.lognormvariate(math.log(median), 0.3)
                    account.direct_debits.append(
                        (label, amount, seasonal, self.rng.randint(12, 22))
                    )
            account.saves_monthly = self.rng.random() < 0.5
        elif profile == "business_current":
            employees = (
                self.rng.randint(2, 30) if customer.segment == "sme" else self.rng.randint(40, 400)
            )
            account.income = employees * self.rng.lognormvariate(math.log(480_000), 0.2)
            account.income_label = "Bérkifizetés"
        elif profile == "savings":
            account.saves_monthly = self.rng.random() < 0.5
        elif profile == "credit_card":
            limit = self.rng.uniform(200_000, 1_000_000) * amount_factor
            account.credit_limit = int(round(limit / 50_000) * 50_000) or 50_000

        # A personal FX account has a debit card too: its card spend is the foreign merchants'
        # traffic (_card_row). Without one, foreign merchants would have no transactions at all.
        has_card = profile in ("credit_card", "personal_current", "personal_fx")
        if profile == "business_current":
            has_card = self.rng.random() < 0.7
        if has_card:
            issued = opened
            last_day = account.closed or self.end
            while True:
                expires = month_end(add_months(issued, CARD_VALIDITY_MONTHS))
                account.cards.append(Card(self._next_card_id(), issued, expires))
                if expires > last_day:
                    break
                issued = expires
        self.accounts.append(account)

    def _next_card_id(self) -> int:
        self._card_seq += 1
        return self._card_seq

    def _build_loans(self) -> None:
        loan_id = 0
        for account in self.accounts:
            if account.profile != "loan":
                continue
            loan_id += 1
            product = PRODUCTS_BY_KEY[account.product_key]
            factor = SEGMENT_AMOUNT_FACTOR[account.customer.segment]
            if product.product_type == "mortgage":
                principal = self.rng.uniform(8e6, 45e6) * factor
                term = self.rng.choice((120, 180, 240, 300))
            elif product.product_type == "personal_loan":
                principal = self.rng.uniform(0.4e6, 6e6) * factor
                term = self.rng.choice((12, 24, 36, 48, 60, 72, 84))
            else:
                principal = self.rng.uniform(5e6, 60e6) * factor
                term = self.rng.choice((24, 36, 48, 60))
            principal = round(principal, -4)
            rate = max(0.01, product.interest_rate + self.rng.uniform(-0.015, 0.015))
            monthly = rate / 12
            installment = round(principal * monthly / (1 - (1 + monthly) ** -term))

            dues = [add_months(account.opened, seq) for seq in range(1, term + 1)]
            past_due = [d for d in dues if d <= self.end]
            first_unpaid = self._first_unpaid_installment(account, product.product_type, past_due)
            closed = first_unpaid is None and len(past_due) == term
            if closed:
                account.status, account.closed = "closed", dues[-1]
            self._loan_rows.append(
                (
                    loan_id,
                    account.account_id,
                    f"{principal:.2f}",
                    f"{rate:.4f}",
                    term,
                    account.opened,
                    "closed" if closed else "active",
                )
            )
            for seq, due in enumerate(dues, start=1):
                paid, paid_at = 0, None
                if due <= self.end and (first_unpaid is None or seq < first_unpaid):
                    paid = installment
                    paid_at = min(due + timedelta(days=self.rng.randint(-5, 3)), self.end)
                elif seq == first_unpaid and self.rng.random() < 0.3:  # partial payment
                    paid = round(installment * self.rng.uniform(0.2, 0.7))
                    paid_at = min(due + timedelta(days=self.rng.randint(0, 10)), self.end)
                self._installment_rows.append(
                    (loan_id, seq, due, f"{installment:.2f}", f"{paid:.2f}", paid_at)
                )

    def _first_unpaid_installment(
        self, account: Account, product_type: str, past_due: list[date]
    ) -> int | None:
        """Pick which installment a delinquent loan stopped paying at (None: pays on time)."""
        probability = DELINQUENCY_RATE[product_type] * RISK_MULTIPLIER[account.customer.risk]
        if self.rng.random() >= probability:
            return None
        low, high, _ = self.rng.choices(DPD_BUCKETS, [b[2] for b in DPD_BUCKETS])[0]
        candidates = [
            seq for seq, due in enumerate(past_due, start=1) if low <= (self.end - due).days <= high
        ]
        return self.rng.choice(candidates) if candidates else None

    # --- transactions -----------------------------------------------------------------

    def _day_weights(self, month: date) -> tuple[list[date], list[float]]:
        days, weights = [], []
        day = month
        while day.month == month.month:
            weight = WEEKDAY_FACTOR[day.weekday()]
            if day in self._holidays:
                weight *= HOLIDAY_FACTOR
            elif day.month == 12 and day.day <= 23:
                weight *= 1.3  # the run-up to Christmas
            days.append(day)
            weights.append(weight)
            day += timedelta(days=1)
        return days, weights

    def _active_days(self, account: Account, month: date) -> tuple[date, date] | None:
        low = max(month, account.opened)
        high = min(month_end(month), account.closed or self.end, self.end)
        return (low, high) if low <= high else None

    def _card_factor(self, account: Account, month: date) -> float:
        factor = MONTH_FACTOR[month.month] * SEGMENT_CARD_FACTOR[account.customer.segment]
        if month in self.story_months and account.customer.branch.code == GROWTH_STORY_BRANCH:
            factor *= GROWTH_STORY_FACTOR
        return factor

    def _scheduled_count(self, account: Account) -> float:
        profile = account.profile
        count = 0.0
        if account.product_key in MONTHLY_FEE:
            count += 1
        if account.income:
            count += 1
        count += len(account.direct_debits)
        if profile in ("savings", "credit_card"):
            count += 1  # interest / repayment
        if account.saves_monthly:
            count += 1
        return count

    def calibrate(self) -> float:
        """Activity level that makes the expected transaction count hit the scale's target."""
        scheduled = variable = 0.0
        for account in self.accounts:
            rates = VARIABLE_RATES[account.profile]
            if not rates:
                continue
            for month in self.months:
                active = self._active_days(account, month)
                if active is None:
                    continue
                share = ((active[1] - active[0]).days + 1) / month_end(month).day
                scheduled += share * self._scheduled_count(account)
                weight = sum(r for kind, r in rates.items() if kind != "card")
                if account.cards:
                    weight += rates.get("card", 0.0) * self._card_factor(account, month)
                variable += share * weight
        if variable == 0:
            return 0.0
        return max(0.5, (self.scale.transactions - scheduled) / variable)

    def _poisson(self, mean: float) -> int:
        if mean <= 0:
            return 0
        if mean > 30:
            return max(0, round(self.tx_rng.gauss(mean, math.sqrt(mean))))
        limit, k, p = math.exp(-mean), 0, self.tx_rng.random()
        while p > limit:
            k += 1
            p *= self.tx_rng.random()
        return k

    def transactions(self, activity: float | None = None) -> Iterator[Row]:
        """Stream the transaction rows; the accounts are visited in id order."""
        if activity is None:
            activity = self.calibrate()
        self.tx_rng = self._stream_rng("transactions")
        month_days = {month: self._day_weights(month) for month in self.months}
        for account in self.accounts:
            if account.profile == "loan":
                continue
            previous_card_spend = 0.0
            for month in self.months:
                active = self._active_days(account, month)
                if active is None:
                    previous_card_spend = 0.0
                    continue
                days, weights = month_days[month]
                low, high = active[0].day - 1, active[1].day
                days, cum = days[low:high], list(accumulate(weights[low:high]))
                share = len(days) / len(month_days[month][0])
                rows = self._account_month(account, month, days, cum, share, activity)
                previous_card_spend = yield from self._with_repayment(
                    account, month, days, rows, previous_card_spend
                )

    def _with_repayment(
        self,
        account: Account,
        month: date,
        days: list[date],
        rows: list[Row],
        previous_card_spend: float,
    ) -> Generator[Row, None, float]:
        """Yield the month's rows; credit cards also get last month's repayment on the 5th.

        Returns the month's card spending (positive), which the next month repays.
        """
        if account.profile == "credit_card" and previous_card_spend > 0:
            day = month.replace(day=5)
            if days[0] <= day <= days[-1]:
                yield self._row(
                    account, day, 9, previous_card_spend, "transfer", "Hitelkártya-törlesztés"
                )
        spend = 0.0
        for row in rows:
            if row[COL_CHANNEL] == "card":
                spend -= float(str(row[COL_AMOUNT]))
            yield row
        return spend

    def _account_month(
        self,
        account: Account,
        month: date,
        days: list[date],
        cum: list[float],
        share: float,
        activity: float,
    ) -> list[Row]:
        rng = self.tx_rng
        rows: list[Row] = []
        customer = account.customer
        years = (month - self.start).days / 365.25
        price = (1 + ANNUAL_PRICE_GROWTH) ** years
        fx = 1.0 if account.currency == "HUF" else FX_START[account.currency]
        amount_factor = SEGMENT_AMOUNT_FACTOR[customer.segment] * price / fx
        first, last = days[0], days[-1]

        def on(day_of_month: int) -> date | None:
            day = month.replace(day=min(day_of_month, month_end(month).day))
            return day if first <= day <= last else None

        # Scheduled events
        if account.income:
            day = on(10 if account.income_label != "Nyugdíj" else 12)
            if day is not None:
                sign = -1 if account.income_label == "Bérkifizetés" else 1
                amount = account.income * price * rng.uniform(0.97, 1.03)
                if month.month == 12 and account.income_label == "Munkabér" and rng.random() < 0.3:
                    amount *= 1.6  # year-end bonus
                rows.append(
                    self._row(account, day, 8, sign * amount, "transfer", account.income_label)
                )
        for label, base, seasonal, due_day in account.direct_debits:
            day = on(due_day)
            if day is not None:
                winter = 1.8 if seasonal and month.month in (11, 12, 1, 2, 3) else 1.0
                amount = -base * winter * price * rng.uniform(0.9, 1.1)
                rows.append(self._row(account, day, 6, amount, "direct_debit", label))
        if account.saves_monthly:
            day = on(11)
            if day is not None:
                amount = rng.lognormvariate(math.log(45_000), 0.5) * amount_factor
                sign = 1 if account.profile == "savings" else -1
                rows.append(
                    self._row(account, day, 9, sign * amount, "transfer", "Rendszeres megtakarítás")
                )
        if account.profile == "savings" and last == month_end(month):
            median = 40_000 if customer.kind == "company" else 3_000
            amount = rng.lognormvariate(math.log(median), 0.6) * amount_factor
            rows.append(self._row(account, last, 23, amount, "interest", "Kamatjóváírás"))
        fee = MONTHLY_FEE.get(account.product_key)
        if fee is not None and last == month_end(month):
            if account.product_key == "business_current" and customer.segment == "corporate":
                fee = 29_000
            rows.append(self._row(account, last, 22, -fee, "fee", "Számlavezetési díj"))

        # Variable events
        for kind, rate in VARIABLE_RATES[account.profile].items():
            mean = activity * rate * share
            if kind == "card":
                if not account.cards:
                    continue
                mean *= self._card_factor(account, month)
            n = self._poisson(mean)
            if n == 0:
                continue
            for day in rng.choices(days, cum_weights=cum, k=n):
                if kind == "card":
                    rows.append(self._card_row(account, day, amount_factor))
                elif kind == "atm":
                    card_id = account.card_on(day)
                    amount = rng.choices(ATM_AMOUNTS, ATM_WEIGHTS)[0]
                    if customer.segment == "premium":
                        amount *= 2
                    rows.append(
                        self._row(
                            account,
                            day,
                            rng.randrange(7, 22),
                            -amount,
                            "atm",
                            "ATM-készpénzfelvétel",
                            card_id,
                        )
                    )
                elif kind == "transfer_out":
                    amount = rng.lognormvariate(math.log(35_000), 0.9) * amount_factor
                    if customer.kind == "company":
                        amount *= 10
                    rows.append(
                        self._row(
                            account, day, rng.randrange(8, 20), -amount, "transfer", "Átutalás"
                        )
                    )
                else:
                    amount = rng.lognormvariate(math.log(25_000), 0.9) * amount_factor
                    if customer.kind == "company":
                        amount *= 25
                    rows.append(
                        self._row(
                            account,
                            day,
                            rng.randrange(8, 18),
                            amount,
                            "transfer",
                            "Bejövő átutalás",
                        )
                    )
        return rows

    def _card_row(self, account: Account, day: date, amount_factor: float) -> Row:
        rng = self.tx_rng
        if account.profile == "personal_fx":
            tilt_key = "foreign"
        elif account.customer.kind == "company":
            tilt_key = "company"
        else:
            tilt_key = account.customer.segment
        codes, cum = self._category_choice(tilt_key)
        code = codes[bisect.bisect_right(cum, rng.random() * cum[-1])]
        category = CATEGORIES_BY_CODE[code]
        pool = self._foreign_by_category if tilt_key == "foreign" else self._merchants_by_category
        merchants, merchant_cum = pool[code]
        merchant_id = merchants[bisect.bisect_right(merchant_cum, rng.random() * merchant_cum[-1])]
        amount = category.median_huf * rng.lognormvariate(0.0, category.sigma) * amount_factor
        return self._row(
            account,
            day,
            7 + bisect.bisect_right(CARD_HOUR_CUM, rng.random() * CARD_HOUR_CUM[-1]),
            -amount,
            "card",
            "Kártyás vásárlás",
            account.card_on(day),
            merchant_id,
        )

    def _category_choice(self, tilt_key: str) -> tuple[list[str], list[float]]:
        cache = self._category_cache
        if tilt_key not in cache:
            if tilt_key == "foreign":
                categories = [c for c in MERCHANT_CATEGORIES if c.foreign]
                tilt: dict[str, float] = {}
            else:
                categories = list(MERCHANT_CATEGORIES)
                tilt = CATEGORY_TILT.get(tilt_key, {})
            cache[tilt_key] = (
                [c.code for c in categories],
                list(accumulate(c.weight * tilt.get(c.code, 1.0) for c in categories)),
            )
        return cache[tilt_key]

    def _row(
        self,
        account: Account,
        day: date,
        hour: int,
        amount: float,
        channel: str,
        description: str,
        card_id: int | None = None,
        merchant_id: int | None = None,
    ) -> Row:
        decimals = 0 if account.currency == "HUF" else 2
        value = round(amount, decimals) or (1 if amount > 0 else -1)
        booked_at = (
            f"{day} {hour:02d}:{self.tx_rng.randrange(60):02d}:{self.tx_rng.randrange(60):02d}"
        )
        return (
            booked_at,
            account.account_id,
            account.customer.branch_id,
            card_id,
            merchant_id,
            f"{value:.2f}",
            account.currency,
            channel,
            description,
        )
