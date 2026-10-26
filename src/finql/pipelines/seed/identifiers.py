"""Hungarian identifier formats with valid check digits (IBAN, tax numbers)."""

import random
from datetime import date

# Not an assigned GIRO bank code, so a generated IBAN cannot belong to a real account.
BANK_CODE = "999"
_TAX_EPOCH = date(1867, 1, 1)


def _weighted_check_digit(digits: str) -> str:
    """Hungarian account-number check digit: weights 9, 7, 3, 1 repeating, mod 10."""
    total = sum(int(d) * (9, 7, 3, 1)[i % 4] for i, d in enumerate(digits))
    return str((10 - total % 10) % 10)


def iban(branch_id: int, account_id: int) -> str:
    """HU IBAN: HU + 2 check digits + 24-digit account number (8 + 16 digits, each with a check)."""
    branch = f"{BANK_CODE}{1000 + branch_id:04d}"
    # x → k·x mod 10^15 is a bijection when k is coprime to 10, so numbers stay unique
    # but do not look sequential.
    account = f"{(account_id * 482_716_359_281_473 + 1_000_003) % 10**15:015d}"
    bban = branch + _weighted_check_digit(branch) + account + _weighted_check_digit(account)
    check = 98 - int(bban + "173000") % 97  # "HU00" moved to the end, H=17, U=30
    return f"HU{check:02d}{bban}"


def is_valid_iban(value: str) -> bool:
    rearranged = value[4:] + value[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(numeric) % 97 == 1


def personal_tax_id(birth_date: date, rng: random.Random) -> str:
    """Adóazonosító jel: 8, days since 1867-01-01, 3 random digits, weighted mod-11 check."""
    days = (birth_date - _TAX_EPOCH).days
    while True:
        body = f"8{days:05d}{rng.randrange(1000):03d}"
        check = sum(int(d) * i for i, d in enumerate(body, start=1)) % 11
        if check < 10:  # 10 would be invalid; draw another serial number
            return body + str(check)


def company_tax_number(rng: random.Random, county_code: int) -> str:
    """Adószám: 7 digits + check (weights 9, 7, 3, 1), VAT code, county code: 12345678-2-41."""
    base = f"{rng.randrange(10_000_000):07d}"
    total = sum(int(d) * w for d, w in zip(base, (9, 7, 3, 1, 9, 7, 3), strict=True))
    return f"{base}{(10 - total % 10) % 10}-{rng.choice((1, 2, 2, 2, 3))}-{county_code:02d}"
