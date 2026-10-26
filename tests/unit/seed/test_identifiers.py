import random
import re
from datetime import date

from finql.pipelines.seed import identifiers


def test_iban_has_valid_check_digits_and_format() -> None:
    ibans = [
        identifiers.iban(branch_id, account_id)
        for branch_id in (1, 20)
        for account_id in range(1, 2001)
    ]

    assert all(re.fullmatch(r"HU[0-9]{26}", value) for value in ibans)
    assert all(identifiers.is_valid_iban(value) for value in ibans)
    assert len(set(ibans)) == len(ibans)


def test_iban_validation_rejects_a_typo() -> None:
    value = identifiers.iban(3, 42)
    typo = value[:10] + str((int(value[10]) + 1) % 10) + value[11:]

    assert not identifiers.is_valid_iban(typo)


def test_iban_bban_blocks_pass_the_hungarian_account_check() -> None:
    bban = identifiers.iban(5, 1234)[4:]
    for block in (bban[:8], bban[8:]):
        weights = [(9, 7, 3, 1)[i % 4] for i in range(len(block))]
        assert sum(int(d) * w for d, w in zip(block, weights, strict=True)) % 10 == 0


def test_personal_tax_id_encodes_birth_date_and_check_digit() -> None:
    rng = random.Random(1)
    birth_date = date(1985, 3, 15)

    for _ in range(200):
        tax_id = identifiers.personal_tax_id(birth_date, rng)
        assert re.fullmatch(r"8[0-9]{9}", tax_id)
        assert int(tax_id[1:6]) == (birth_date - date(1867, 1, 1)).days
        check = sum(int(d) * i for i, d in enumerate(tax_id[:9], start=1)) % 11
        assert check == int(tax_id[9])


def test_company_tax_number_format_and_check_digit() -> None:
    rng = random.Random(2)

    for _ in range(200):
        value = identifiers.company_tax_number(rng, county_code=41)
        assert re.fullmatch(r"[0-9]{8}-[1-5]-41", value)
        digits = value[:8]
        weighted = sum(int(d) * w for d, w in zip(digits, (9, 7, 3, 1, 9, 7, 3, 1), strict=True))
        assert weighted % 10 == 0
