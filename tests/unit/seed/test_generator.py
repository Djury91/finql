from collections import defaultdict
from datetime import date
from functools import cache

from finql.pipelines.seed.generator import Account, SeedGenerator
from finql.pipelines.seed.reference import GROWTH_STORY_BRANCH
from finql.pipelines.seed.scales import SCALES, Scale

TINY = SCALES["tiny"]
# Long enough for a quarter-over-quarter comparison, small enough for a unit test.
SIX_MONTHS = Scale("six", customers=1500, transactions=120_000, months=6, branches=6, merchants=150)


@cache
def tiny() -> tuple[SeedGenerator, tuple[tuple[object, ...], ...]]:
    generator = SeedGenerator(TINY, seed=42)
    return generator, tuple(generator.transactions())


def test_same_seed_gives_same_rows() -> None:
    first, second = SeedGenerator(TINY, seed=7), SeedGenerator(TINY, seed=7)

    assert list(first.customer_rows()) == list(second.customer_rows())
    assert list(first.account_rows()) == list(second.account_rows())
    assert list(first.transactions()) == list(second.transactions())


def test_streams_do_not_depend_on_read_order() -> None:
    reads_customers_first = SeedGenerator(TINY, seed=7)
    list(reads_customers_first.customer_rows())
    list(reads_customers_first.card_rows())
    transactions_only = SeedGenerator(TINY, seed=7)

    assert list(reads_customers_first.transactions()) == list(transactions_only.transactions())


def test_transaction_count_lands_near_the_target() -> None:
    _, rows = tiny()

    assert abs(len(rows) - TINY.transactions) / TINY.transactions < 0.1


def test_transactions_fall_inside_the_account_lifetime() -> None:
    generator, rows = tiny()
    accounts: dict[object, Account] = {a.account_id: a for a in generator.accounts}

    for booked_at, account_id, branch_id, card_id, _, amount, currency, channel, _ in rows:
        account = accounts[account_id]
        day = date.fromisoformat(str(booked_at)[:10])
        assert account.opened <= day <= (account.closed or TINY.business_date)
        assert branch_id == account.customer.branch_id
        assert currency == account.currency
        assert float(str(amount)) != 0
        if channel == "card":
            assert card_id is not None and card_id == account.card_on(day)
        if channel in ("fee", "direct_debit", "atm", "card"):
            assert float(str(amount)) < 0


def test_loans_are_annuities_and_some_are_past_due() -> None:
    generator, _ = tiny()
    installments: dict[object, list[tuple[object, ...]]] = defaultdict(list)
    for row in generator.installment_rows():
        installments[row[0]].append(row)

    for loan_id, _, _, _, term, _, status in generator.loan_rows():
        rows = installments[loan_id]
        assert len(rows) == term
        assert len({row[3] for row in rows}) == 1  # equal installments
        for _, _, due, amount_due, amount_paid, paid_at in rows:
            assert 0 <= float(str(amount_paid)) <= float(str(amount_due))
            assert (paid_at is None) == (float(str(amount_paid)) == 0)
            if isinstance(due, date) and due > TINY.business_date:
                assert paid_at is None
        if status == "closed":
            assert all(row[5] is not None for row in rows)


def test_delinquency_rate_is_a_few_percent() -> None:
    generator = SeedGenerator(Scale("loans", 4000, 1, 1, 6, 30), seed=1)
    past_due: set[object] = set()
    for loan_id, _, due, amount_due, amount_paid, _ in generator.installment_rows():
        if isinstance(due, date) and due <= generator.business_date() and amount_paid != amount_due:
            past_due.add(loan_id)
    active = [row for row in generator.loan_rows() if row[6] == "active"]

    assert 0.02 < len(past_due) / len(active) < 0.07


def test_growth_story_branch_leads_quarter_over_quarter() -> None:
    generator = SeedGenerator(SIX_MONTHS, seed=3)
    spend: dict[tuple[object, int], float] = defaultdict(float)
    for booked_at, _, branch_id, _, _, amount, currency, channel, _ in generator.transactions():
        if channel == "card" and currency == "HUF":
            quarter = (int(str(booked_at)[5:7]) - 1) // 3
            spend[(branch_id, quarter)] -= float(str(amount))

    growth = {b: spend[(b, 2)] / spend[(b, 1)] - 1 for b in range(1, SIX_MONTHS.branches + 1)}
    codes = {row[0]: row[1] for row in generator.branch_rows()}
    leader = max(growth, key=lambda b: growth[b])

    assert codes[leader] == GROWTH_STORY_BRANCH


def test_foreign_currency_accounts_spend_at_foreign_merchants() -> None:
    # Regression: personal FX accounts had no card, so foreign merchants had no transactions and
    # a question about card spend abroad had an empty answer.
    generator, rows = tiny()
    foreign = {row[0] for row in generator.merchant_rows() if row[5] != "HU"}
    fx_card_rows = [row for row in rows if row[7] == "card" and row[6] != "HUF"]

    assert fx_card_rows
    assert {row[4] for row in fx_card_rows} <= foreign
