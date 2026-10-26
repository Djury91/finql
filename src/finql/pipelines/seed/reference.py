"""Fixed reference data of the synthetic bank: branches, products, merchant categories, calendar."""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Branch:
    code: str
    name: str
    city: str
    region: str
    weight: float = 1.0  # relative share of customers


# The first six are used by the `tiny` scale, so the test data has Budapest, an agglomeration
# branch and two regional centres (the eval's "Budaörs vs Pécs" example needs both).
BRANCHES = (
    Branch("BUD01", "Budapest Belváros fiók", "Budapest", "Budapest", 2.5),
    Branch("BUO01", "Budaörsi fiók", "Budaörs", "Pest", 1.2),
    Branch("PEC01", "Pécsi fiók", "Pécs", "Dél-Dunántúl"),
    Branch("DEB01", "Debreceni fiók", "Debrecen", "Észak-Alföld", 1.3),
    Branch("GYO01", "Győri fiók", "Győr", "Nyugat-Dunántúl"),
    Branch("BUD02", "Budapest Újbuda fiók", "Budapest", "Budapest", 2.0),
    Branch("SZE01", "Szegedi fiók", "Szeged", "Dél-Alföld", 1.2),
    Branch("MIS01", "Miskolci fiók", "Miskolc", "Észak-Magyarország"),
    Branch("BUD03", "Budapest Angyalföld fiók", "Budapest", "Budapest", 1.8),
    Branch("KEC01", "Kecskeméti fiók", "Kecskemét", "Dél-Alföld"),
    Branch("SZF01", "Székesfehérvári fiók", "Székesfehérvár", "Közép-Dunántúl"),
    Branch("NYI01", "Nyíregyházi fiók", "Nyíregyháza", "Észak-Alföld"),
    Branch("SZO01", "Szombathelyi fiók", "Szombathely", "Nyugat-Dunántúl", 0.8),
    Branch("VES01", "Veszprémi fiók", "Veszprém", "Közép-Dunántúl", 0.8),
    Branch("EGE01", "Egri fiók", "Eger", "Észak-Magyarország", 0.7),
    Branch("KAP01", "Kaposvári fiók", "Kaposvár", "Dél-Dunántúl", 0.7),
    Branch("SZN01", "Szolnoki fiók", "Szolnok", "Észak-Alföld", 0.8),
    Branch("ERD01", "Érdi fiók", "Érd", "Pest", 0.9),
    Branch("ZAL01", "Zalaegerszegi fiók", "Zalaegerszeg", "Nyugat-Dunántúl", 0.6),
    Branch("BEK01", "Békéscsabai fiók", "Békéscsaba", "Dél-Alföld", 0.6),
)

# A quarter of the customers live in a nearby town instead of the branch's city.
REGION_TOWNS = {
    "Budapest": ("Budapest",),
    "Pest": ("Törökbálint", "Biatorbágy", "Budakeszi", "Diósd", "Százhalombatta", "Szentendre"),
    "Dél-Dunántúl": ("Komló", "Mohács", "Szigetvár", "Siófok", "Barcs"),
    "Észak-Alföld": (
        "Hajdúszoboszló",
        "Balmazújváros",
        "Nyírbátor",
        "Kisvárda",
        "Törökszentmiklós",
    ),
    "Nyugat-Dunántúl": ("Mosonmagyaróvár", "Sopron", "Kőszeg", "Keszthely", "Csorna"),
    "Dél-Alföld": ("Hódmezővásárhely", "Makó", "Kiskunfélegyháza", "Gyula", "Baja"),
    "Észak-Magyarország": ("Ózd", "Kazincbarcika", "Tiszaújváros", "Gyöngyös", "Hatvan"),
    "Közép-Dunántúl": ("Dunaújváros", "Pápa", "Ajka", "Tata", "Várpalota"),
}
# County code in the company tax number (adószám), by region.
REGION_COUNTY_CODE = {
    "Budapest": 41,
    "Pest": 13,
    "Dél-Dunántúl": 2,
    "Észak-Alföld": 9,
    "Nyugat-Dunántúl": 8,
    "Dél-Alföld": 6,
    "Észak-Magyarország": 5,
    "Közép-Dunántúl": 7,
}

# Story: card spending at this branch grows 40% in the last quarter of the period.
GROWTH_STORY_BRANCH = "DEB01"
GROWTH_STORY_FACTOR = 1.40


@dataclass(frozen=True)
class Product:
    key: str
    product_type: str
    name: str
    currency: str
    interest_rate: float  # annual, as a fraction


PRODUCTS = (
    Product("retail_current", "current_account", "Lakossági számlacsomag", "HUF", 0.0001),
    Product("premium_current", "current_account", "Prémium számlacsomag", "HUF", 0.0005),
    Product("retail_eur", "current_account", "Lakossági euró devizaszámla", "EUR", 0.0),
    Product("savings", "savings", "Megtakarítási számla", "HUF", 0.0350),
    Product("credit_card", "credit_card", "Hitelkártya", "HUF", 0.3290),
    Product("personal_loan", "personal_loan", "Személyi kölcsön", "HUF", 0.1490),
    Product("mortgage", "mortgage", "Lakáshitel", "HUF", 0.0690),
    Product("business_current", "current_account", "Vállalkozói számlacsomag", "HUF", 0.0),
    Product("business_eur", "current_account", "Vállalati euró devizaszámla", "EUR", 0.0),
    Product("business_usd", "current_account", "Vállalati dollár devizaszámla", "USD", 0.0),
    Product("business_deposit", "savings", "Vállalati lekötött betét", "HUF", 0.0400),
    Product("business_card", "credit_card", "Üzleti hitelkártya", "HUF", 0.2690),
    Product("business_loan", "business_loan", "Vállalkozói hitel", "HUF", 0.0990),
)
PRODUCT_IDS = {product.key: product_id for product_id, product in enumerate(PRODUCTS, start=1)}
PRODUCTS_BY_KEY = {product.key: product for product in PRODUCTS}


@dataclass(frozen=True)
class MerchantCategory:
    code: str
    mcc: int
    words: tuple[str, ...]  # used in merchant names
    weight: float  # share of card transactions
    median_huf: float  # median ticket size
    sigma: float  # log-normal spread
    foreign: bool = False  # also has merchants abroad


MERCHANT_CATEGORIES = (
    MerchantCategory(
        "grocery", 5411, ("ABC", "Élelmiszer", "Csemege", "Diszkont"), 0.30, 6500, 0.8, True
    ),
    MerchantCategory(
        "fast_food", 5814, ("Büfé", "Pékség", "Kávézó", "Gyorsétterem"), 0.10, 2600, 0.6
    ),
    MerchantCategory("restaurant", 5812, ("Étterem", "Vendéglő", "Bisztró"), 0.08, 9500, 0.6, True),
    MerchantCategory("fuel", 5541, ("Benzinkút", "Töltőállomás"), 0.08, 18000, 0.4),
    MerchantCategory("online_retail", 5999, ("Webáruház", "Online"), 0.07, 12000, 1.0),
    MerchantCategory("transport", 4121, ("Taxi", "Személyszállítás"), 0.06, 3500, 0.6),
    MerchantCategory("pharmacy", 5912, ("Patika", "Gyógyszertár"), 0.05, 4500, 0.7),
    MerchantCategory("clothing", 5651, ("Divat", "Ruházat", "Butik"), 0.05, 14000, 0.7, True),
    MerchantCategory(
        "home_garden", 5200, ("Barkács", "Lakberendezés", "Kertészet"), 0.04, 15000, 0.9
    ),
    MerchantCategory("electronics", 5732, ("Műszaki", "Elektronika"), 0.03, 38000, 1.0),
    MerchantCategory("beauty", 7230, ("Fodrászat", "Szépségszalon"), 0.03, 8000, 0.5),
    MerchantCategory("entertainment", 7832, ("Mozi", "Szórakoztató"), 0.03, 6000, 0.5),
    MerchantCategory("hotel", 7011, ("Hotel", "Panzió", "Szálloda"), 0.02, 48000, 0.8, True),
    MerchantCategory("travel", 4722, ("Utazási Iroda", "Utazás"), 0.01, 95000, 0.7, True),
)

# Category preference multipliers per spender profile (missing = 1.0).
CATEGORY_TILT: dict[str, dict[str, float]] = {
    "retail": {},
    "premium": {
        "grocery": 0.8,
        "restaurant": 1.7,
        "electronics": 1.5,
        "hotel": 3.0,
        "travel": 3.0,
        "clothing": 1.4,
    },
    "company": {
        "grocery": 0.3,
        "fast_food": 0.5,
        "fuel": 4.0,
        "online_retail": 2.0,
        "restaurant": 1.5,
        "electronics": 2.5,
        "beauty": 0.1,
        "entertainment": 0.2,
        "clothing": 0.2,
    },
}

FOREIGN_CITIES = (
    ("AT", "Wien"),
    ("AT", "Graz"),
    ("DE", "München"),
    ("DE", "Berlin"),
    ("HR", "Split"),
    ("HR", "Zagreb"),
    ("IT", "Roma"),
    ("IT", "Venezia"),
    ("ES", "Barcelona"),
    ("FR", "Paris"),
)

# Approximate MNB mid rates at the start of the period; a random walk moves them daily.
FX_START = {"EUR": 395.0, "USD": 362.0}

# Seasonality of card spending by calendar month (December: Christmas shopping).
MONTH_FACTOR = {
    1: 0.88,
    2: 0.90,
    3: 1.00,
    4: 1.00,
    5: 1.02,
    6: 1.03,
    7: 1.06,
    8: 1.06,
    9: 0.98,
    10: 1.00,
    11: 1.05,
    12: 1.35,
}
# Monday … Sunday
WEEKDAY_FACTOR = (0.90, 0.90, 0.95, 1.00, 1.20, 1.30, 0.75)
HOLIDAY_FACTOR = 0.35

# Story: the account-opening campaign doubles new accounts in this month.
CAMPAIGN_MONTH = date(2025, 3, 1)
CAMPAIGN_FACTOR = 2.2


def easter_sunday(year: int) -> date:
    """Gregorian Easter (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def hungarian_holidays(year: int) -> frozenset[date]:
    """Public holidays in Hungary (Munka törvénykönyve 102. §)."""
    easter = easter_sunday(year)
    fixed = [(1, 1), (3, 15), (5, 1), (8, 20), (10, 23), (11, 1), (12, 25), (12, 26)]
    movable = [easter - timedelta(days=2), easter + timedelta(days=1), easter + timedelta(days=50)]
    return frozenset([date(year, m, d) for m, d in fixed] + movable)
