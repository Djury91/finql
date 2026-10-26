-- Szemantikai leírások: ebből tanulja meg az LLM a sémát (3. fázis: schema_context.py).
-- Minden nézetnek és oszlopnak van leírása; ezt teszt ellenőrzi.
-- Elv: mit jelent az érték, milyen egységben van, milyen értékeket vehet fel, és mire figyeljen.

-- branches ---------------------------------------------------------------------------------
COMMENT ON VIEW analytics.branches IS
    'A bank fiókjai. Egy sor egy fiók.';
COMMENT ON COLUMN analytics.branches.branch_id IS 'Fiókazonosító.';
COMMENT ON COLUMN analytics.branches.code IS 'Rövid fiókkód, pl. BUD01, DEB01, PEC01.';
COMMENT ON COLUMN analytics.branches.name IS 'A fiók neve, pl. ''Debreceni fiók''.';
COMMENT ON COLUMN analytics.branches.city IS 'A fiók városa.';
COMMENT ON COLUMN analytics.branches.region IS
    'Régió: Budapest, Pest, Közép-Dunántúl, Nyugat-Dunántúl, Dél-Dunántúl, Észak-Magyarország, Észak-Alföld, Dél-Alföld.';

-- products ---------------------------------------------------------------------------------
COMMENT ON VIEW analytics.products IS
    'A bank termékei (számlacsomagok, megtakarítás, hitelkártya, hitelek). Egy sor egy termék.';
COMMENT ON COLUMN analytics.products.product_id IS 'Termékazonosító.';
COMMENT ON COLUMN analytics.products.product_type IS
    'Terméktípus: current_account (folyószámla), savings (megtakarítás, betét), credit_card (hitelkártya), personal_loan (személyi kölcsön), mortgage (lakáshitel), business_loan (vállalkozói hitel).';
COMMENT ON COLUMN analytics.products.name IS 'A termék neve, pl. ''Prémium számlacsomag''.';
COMMENT ON COLUMN analytics.products.currency IS 'Devizanem (ISO 4217): HUF, EUR, USD.';
COMMENT ON COLUMN analytics.products.interest_rate IS
    'Éves kamatláb törtként: 0.0690 = 6,9%. Százalékhoz szorozd 100-zal.';

-- merchants --------------------------------------------------------------------------------
COMMENT ON VIEW analytics.merchants IS
    'Kártyaelfogadó kereskedők. Egy sor egy kereskedő.';
COMMENT ON COLUMN analytics.merchants.merchant_id IS 'Kereskedőazonosító.';
COMMENT ON COLUMN analytics.merchants.name IS 'A kereskedő neve.';
COMMENT ON COLUMN analytics.merchants.mcc IS 'Merchant Category Code (ISO 18245), pl. 5411 = élelmiszerbolt.';
COMMENT ON COLUMN analytics.merchants.category IS
    'Kategória: grocery (élelmiszer), fast_food (büfé, pékség, kávézó), restaurant (étterem), fuel (üzemanyag), online_retail (webáruház), transport (taxi, személyszállítás), pharmacy (gyógyszertár), clothing (ruházat), home_garden (barkács, lakberendezés), electronics (műszaki cikk), beauty (fodrász, szépségszalon), entertainment (mozi, szórakozás), hotel (szállás), travel (utazási iroda).';
COMMENT ON COLUMN analytics.merchants.city IS 'A kereskedő városa.';
COMMENT ON COLUMN analytics.merchants.country IS 'Ország (ISO 3166-1 alpha-2), pl. HU, AT, DE, HR.';

-- fx_rates ---------------------------------------------------------------------------------
COMMENT ON VIEW analytics.fx_rates IS
    'MNB-középárfolyamok forintra. Minden naptári napra van sor (hétvégén és ünnepnap az előző munkanapé). A HUF nem szerepel. Átváltáshoz általában elég a transactions.amount_huf.';
COMMENT ON COLUMN analytics.fx_rates.rate_date IS 'Az árfolyam napja.';
COMMENT ON COLUMN analytics.fx_rates.currency IS 'Devizanem: EUR vagy USD.';
COMMENT ON COLUMN analytics.fx_rates.rate_to_huf IS 'Egy egység deviza forintban, pl. 395.12.';

-- business_day -----------------------------------------------------------------------------
COMMENT ON VIEW analytics.business_day IS
    'Az aktuális üzleti nap (egy sor). A „ma”, „idén”, „tavaly”, „az elmúlt 3 hónap” ehhez viszonyítandó, NEM a current_date-hez.';
COMMENT ON COLUMN analytics.business_day.business_date IS 'A bank aktuális üzleti napja (a „mai nap”).';

-- customers --------------------------------------------------------------------------------
COMMENT ON VIEW analytics.customers IS
    'Ügyfelek (magánszemélyek és cégek), személyes adat nélkül. Egy sor egy ügyfél.';
COMMENT ON COLUMN analytics.customers.customer_id IS 'Ügyfélazonosító.';
COMMENT ON COLUMN analytics.customers.customer_type IS 'Ügyféltípus: individual (magánszemély) vagy company (cég).';
COMMENT ON COLUMN analytics.customers.segment IS
    'Ügyfélszegmens: retail (lakossági), premium (prémium lakossági), sme (kis- és középvállalkozás), corporate (nagyvállalat).';
COMMENT ON COLUMN analytics.customers.city IS 'Az ügyfél lakóhelye vagy székhelye (város).';
COMMENT ON COLUMN analytics.customers.age_band IS
    'Korcsoport az üzleti napon: 18-25, 26-35, 36-45, 46-55, 56-65, 66+. Cégnél NULL.';
COMMENT ON COLUMN analytics.customers.home_branch_id IS 'Az ügyfél otthoni fiókja (branches.branch_id).';
COMMENT ON COLUMN analytics.customers.risk_rating IS 'Kockázati besorolás: low (alacsony), medium (közepes), high (magas).';
COMMENT ON COLUMN analytics.customers.customer_since IS 'Az ügyfélkapcsolat kezdete (dátum).';
COMMENT ON COLUMN analytics.customers.is_active IS
    'Aktív ügyfél: van legalább egy nem megszüntetett (active vagy frozen) számlája.';

-- accounts ---------------------------------------------------------------------------------
COMMENT ON VIEW analytics.accounts IS
    'Számlák (folyószámla, megtakarítás, hitelkártya, hitelszámla). Egy sor egy számla. Új számlanyitás = opened_at.';
COMMENT ON COLUMN analytics.accounts.account_id IS 'Számlaazonosító.';
COMMENT ON COLUMN analytics.accounts.customer_id IS 'A számlatulajdonos ügyfél (customers.customer_id).';
COMMENT ON COLUMN analytics.accounts.branch_id IS 'A számlát kezelő fiók (branches.branch_id).';
COMMENT ON COLUMN analytics.accounts.product_id IS 'A számla terméke (products.product_id).';
COMMENT ON COLUMN analytics.accounts.product_type IS
    'Terméktípus (a products.product_type másolata): current_account, savings, credit_card, personal_loan, mortgage, business_loan.';
COMMENT ON COLUMN analytics.accounts.product_name IS 'A termék neve.';
COMMENT ON COLUMN analytics.accounts.currency IS 'A számla devizaneme: HUF, EUR, USD.';
COMMENT ON COLUMN analytics.accounts.status IS 'Állapot: active (aktív), frozen (zárolt), closed (megszüntetett).';
COMMENT ON COLUMN analytics.accounts.is_active IS 'Igaz, ha a számla nincs megszüntetve (status <> ''closed'').';
COMMENT ON COLUMN analytics.accounts.opened_at IS 'A számlanyitás napja.';
COMMENT ON COLUMN analytics.accounts.closed_at IS 'A megszüntetés napja; nyitott számlánál NULL.';
COMMENT ON COLUMN analytics.accounts.credit_limit IS 'Hitelkeret a számla devizájában; csak hitelkártyánál, egyébként NULL.';
COMMENT ON COLUMN analytics.accounts.iban_masked IS 'Maszkolt IBAN, csak az utolsó 4 számjegy látszik.';

-- cards ------------------------------------------------------------------------------------
COMMENT ON VIEW analytics.cards IS
    'Bankkártyák. Egy sor egy kártya; lejáratkor új kártya (új sor) készül ugyanahhoz a számlához.';
COMMENT ON COLUMN analytics.cards.card_id IS 'Kártyaazonosító.';
COMMENT ON COLUMN analytics.cards.account_id IS 'A kártyához tartozó számla (accounts.account_id).';
COMMENT ON COLUMN analytics.cards.card_type IS 'Kártyatípus: debit (betéti) vagy credit (hitelkártya).';
COMMENT ON COLUMN analytics.cards.status IS 'Állapot: active (aktív), blocked (letiltott), expired (lejárt).';
COMMENT ON COLUMN analytics.cards.issued_at IS 'A kibocsátás napja.';
COMMENT ON COLUMN analytics.cards.expires_at IS 'A lejárat napja.';

-- transactions -----------------------------------------------------------------------------
COMMENT ON VIEW analytics.transactions IS
    'Könyvelt számlatranzakciók. Egy sor egy tétel. Az amount előjeles: negatív = terhelés (költés, kifizetés), pozitív = jóváírás. Időszakra szűrésnél a booked_at-et használd (pl. booked_at >= ''2025-09-01'' AND booked_at < ''2025-10-01''): a tábla havi partíciókra bontott, így csak a szükséges hónapokat olvassa.';
COMMENT ON COLUMN analytics.transactions.transaction_id IS 'Tranzakcióazonosító.';
COMMENT ON COLUMN analytics.transactions.account_id IS 'A számla (accounts.account_id).';
COMMENT ON COLUMN analytics.transactions.branch_id IS 'A számlát kezelő fiók (branches.branch_id); fiókszintű összesítéshez nem kell JOIN.';
COMMENT ON COLUMN analytics.transactions.booked_at IS 'A könyvelés időpontja (időzónával). Időszűréshez ezt használd.';
COMMENT ON COLUMN analytics.transactions.booked_date IS 'A könyvelés napja budapesti idő szerint (megjelenítéshez, napi csoportosításhoz).';
COMMENT ON COLUMN analytics.transactions.amount IS
    'Összeg a számla devizájában, előjelesen: negatív = terhelés, pozitív = jóváírás. Devizák közötti összesítéshez az amount_huf-ot használd.';
COMMENT ON COLUMN analytics.transactions.currency IS 'Devizanem: HUF, EUR, USD.';
COMMENT ON COLUMN analytics.transactions.amount_huf IS
    'Az összeg forintban, a könyvelés napi MNB-árfolyamán, előjelesen. Összesítéshez (forgalom, költés) ezt használd. Költésnél: -sum(amount_huf) WHERE amount < 0.';
COMMENT ON COLUMN analytics.transactions.channel IS
    'Csatorna: card (kártyás vásárlás), transfer (átutalás, munkabér, törlesztés), atm (készpénzfelvétel), direct_debit (csoportos beszedés), fee (díj), interest (kamat). Kártyás forgalom/költés: channel = ''card''.';
COMMENT ON COLUMN analytics.transactions.merchant_id IS 'Kereskedő (merchants.merchant_id); csak kártyás tételnél, egyébként NULL.';
COMMENT ON COLUMN analytics.transactions.merchant_name IS 'A kereskedő neve (merchants.name); csak kártyás tételnél.';
COMMENT ON COLUMN analytics.transactions.merchant_category IS 'A kereskedő kategóriája (merchants.category); csak kártyás tételnél.';

-- loans ------------------------------------------------------------------------------------
COMMENT ON VIEW analytics.loans IS
    'Hitelek (személyi kölcsön, lakáshitel, vállalkozói hitel) előre kiszámolt késedelmi mutatókkal, az üzleti napra vetítve. Egy sor egy hitel. Késedelmes hitel: days_past_due > 0.';
COMMENT ON COLUMN analytics.loans.loan_id IS 'Hitelazonosító.';
COMMENT ON COLUMN analytics.loans.account_id IS 'A hitelszámla (accounts.account_id).';
COMMENT ON COLUMN analytics.loans.customer_id IS 'Az adós ügyfél (customers.customer_id).';
COMMENT ON COLUMN analytics.loans.branch_id IS 'A hitelt kezelő fiók (branches.branch_id).';
COMMENT ON COLUMN analytics.loans.product_type IS 'Hiteltípus: personal_loan (személyi kölcsön), mortgage (lakáshitel), business_loan (vállalkozói hitel).';
COMMENT ON COLUMN analytics.loans.product_name IS 'A hiteltermék neve.';
COMMENT ON COLUMN analytics.loans.principal IS 'Folyósított hitelösszeg (tőke) forintban.';
COMMENT ON COLUMN analytics.loans.interest_rate IS 'Éves kamatláb törtként: 0.1490 = 14,9%.';
COMMENT ON COLUMN analytics.loans.term_months IS 'Futamidő hónapban.';
COMMENT ON COLUMN analytics.loans.start_date IS 'A folyósítás napja.';
COMMENT ON COLUMN analytics.loans.status IS 'Állapot: active (élő) vagy closed (visszafizetve, lezárva).';
COMMENT ON COLUMN analytics.loans.remaining_amount IS
    'Még meg nem fizetett törlesztőrészletek összege forintban (tőke + kamat), a lejárt és a jövőbeli részletekkel együtt.';
COMMENT ON COLUMN analytics.loans.overdue_amount IS 'Lejárt, de meg nem fizetett összeg forintban (az üzleti napig esedékes részletekből).';
COMMENT ON COLUMN analytics.loans.days_past_due IS
    'Késedelmes napok száma: az üzleti nap és a legrégebbi lejárt, nem (teljesen) megfizetett részlet esedékessége közötti napok. 0 = nem késik.';
COMMENT ON COLUMN analytics.loans.dpd_bucket IS
    'Késedelmi sáv a days_past_due alapján: ''0'', ''1-30'', ''31-60'', ''61-90'', ''90+''. „30 napnál többet késik” = days_past_due > 30.';

-- monthly_account_summary ------------------------------------------------------------------
COMMENT ON VIEW analytics.monthly_account_summary IS
    'Havi számlaösszesítő (előre számolt, gyors): számla × hónap. Csak azok a hónapok szerepelnek, amelyekben volt tranzakció. Havi trendekhez ezt használd a transactions helyett. A seed betöltésekor frissül.';
COMMENT ON COLUMN analytics.monthly_account_summary.account_id IS 'A számla (accounts.account_id).';
COMMENT ON COLUMN analytics.monthly_account_summary.branch_id IS 'A számlát kezelő fiók (branches.branch_id).';
COMMENT ON COLUMN analytics.monthly_account_summary.month IS 'A hónap első napja (budapesti naptár szerint).';
COMMENT ON COLUMN analytics.monthly_account_summary.tx_count IS 'A hónap tételeinek száma.';
COMMENT ON COLUMN analytics.monthly_account_summary.inflow_huf IS 'Jóváírások összege forintban (pozitív szám).';
COMMENT ON COLUMN analytics.monthly_account_summary.outflow_huf IS 'Terhelések összege forintban (pozitív szám).';
COMMENT ON COLUMN analytics.monthly_account_summary.card_spend_huf IS 'Kártyás költés forintban (pozitív szám).';
