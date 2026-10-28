# 1. Pécsi Péter, branch manager

[← Scenarios](README.md)

**What it shows:** the branch manager sees only his own branch's data (PEC01, Pécs) and can
read only the general policies. The filtering is done by the database (Row-Level Security):
the generated SQL contains no branch filter.

## Sign in

1. **Do:** open `<demo-url>`.

   **Expected:** a yellow bar at the top ("Demó mód, API-kulcs nélkül…", "Demo mode, no API
   key…"), the *Bejelentkezés* (Sign in) card in the middle, and five buttons below it: Pécsi
   Péter, Budaörsi Bea, Elemző Endre, Auditor Aliz, Admin Anna.
2. **Do:** click the **Pécsi Péter – fiókvezető (PEC01)** (branch manager) button.

   **Expected:** "Pécsi Péter" and the *fiókvezető* (branch manager) label at the top right. In
   the middle, "Kérdezz az adatokról vagy a szabályzatokról" ("Ask about the data or the
   policies"), with four example-question buttons below it.

## Data question and policy: own branch only

3. **Do:** click the example question **Hány 90+ napos késedelmes hitelünk van, és mi a teendő a
   szabályzat szerint?** ("How many loans are 90+ days past due, and what does the policy say
   to do?").

   **Expected:** your question moves to the right. Two tool cards appear in the answer, both
   with a green time value (*… ms*):
   - *Adatbázis-lekérdezés* (database query) – "Hány 90+ napos késedelmes hitelünk van?" ("How
     many loans are 90+ days past due?")
   - *Dokumentumkeresés* (document search) – the full question
4. **Do:** click the *Adatbázis-lekérdezés* card.

   **Expected:** the executed SQL and the result:
   ```sql
   SELECT
     COUNT(*) AS loans
   FROM loans
   WHERE
     dpd_bucket = '90+'
   LIMIT 200
   ```
   In the table `loans` = **1**, and below it "1 sor. Napló: #…" ("1 row. Log: #…").
   Note: the SQL has no branch filter, yet it counted only the Pécs loans.
5. **Do:** read the text of the answer.

   **Expected:**
   - "API-kulcs nélküli mód: ezt a választ nem nyelvi modell írta, az eszközök eredményét
     idézi." ("No-API-key mode: this answer was not written by a language model; it quotes the
     tool results.")
   - "Az adatbázis szerint (csak a felhasználó saját fiókja (branch_id = 3)): loans = 1."
     ("According to the database (only the user's own branch (branch_id = 3)): loans = 1.")
   - A quote from the *Követeléskezelési szabályzat – késedelmes hitelek* (Collections policy –
     past-due loans) document, ending in [1].
6. **Do:** click the *Dokumentumkeresés* card.

   **Expected:** three hits, all from the *Követeléskezelési szabályzat – késedelmes hitelek*
   document; the section of [2] is "90 napon túli késedelem" ("Delinquency over 90 days"), the
   section of [3] is "61–90 napos késedelem" ("Delinquency of 61–90 days").
7. **Do:** at the bottom of the answer, click the source: **Követeléskezelési szabályzat –
   késedelmes hitelek** (hatályos: 2026-03-01) (effective: 2026-03-01).

   **Expected:** the quoted passage expands.

## Segments: own branch's customers only

8. **Do:** top left, **Új beszélgetés** (New conversation), then the example question **Hány
   aktív ügyfelünk van szegmensenként?** ("How many active customers do we have per
   segment?"). Expand the *Adatbázis-lekérdezés* card.

   **Expected:** a four-row table:

   | segment | customers |
   |---|---|
   | retail | 340 |
   | premium | 50 |
   | sme | 47 |
   | corporate | 10 |

   The first *Dokumentumkeresés* hit is *Üzleti fogalomtár és mutatók – Ügyfelek és
   szegmensek* (Business glossary and metrics – Customers and segments); the answer quotes the
   definition of an active customer from it.

## Internal policy: the branch manager does not find it

9. **Do:** **Új beszélgetés**, type `Mekkora az NPL-ráta kemény limitje?` ("What is the hard
   limit on the NPL ratio?") into the input box, then press Enter.

   **Expected:** there is only a *Dokumentumkeresés* card, no database query (this is not a
   data question). The three hits:
   - [1] Üzleti fogalomtár és mutatók – Hitelek és késedelem (Business glossary and metrics –
     Loans and delinquency)
   - [2] Pénztári műveletek és készpénzkezelés a fiókban – Hamis vagy gyanús bankjegy (Teller
     operations and cash handling in the branch – Counterfeit or suspicious banknotes)
   - [3] Ügyfél-átvilágítás és a pénzmosás megelőzése – Az átvilágítás lépései (Customer due
     diligence and anti-money laundering – Steps of due diligence)

   The answer quotes the glossary and does not state the limit. The document that has the
   answer, *Hitelportfólió-limitek és kockázati étvágy 2026* (Loan portfolio limits and risk
   appetite 2026), is an internal policy the branch manager cannot read, so the search does not
   return it at all. The same question finds it for the analyst (scenario 3, step 6).

## Free-form question without a key

10. **Do:** **Új beszélgetés**, type `Melyik ügyfelünknek van a legtöbb pénze?` ("Which of our
    customers has the most money?")

    **Expected:** only *Dokumentumkeresés* runs, no database query. Without a key, hand-written
    SQL exists only for the example data questions; a free-form question needs Claude.

## API (optional)

11. **Do:** open `<demo-url>/docs` and click **Authorize**.
    *username*: `pecs@minta-bank.example`, *password*: the shared password shown at the bottom
    of the sign-in page. **Authorize**, then **Close**.

    **Expected:** the padlocks switch to locked.
12. **Do:** `GET /query/history` → **Try it out** → **Execute**.

    **Expected:** `200`, your own earlier questions; every row has `"scope": "branch"` and
    `"branch_id": 3`.
13. **Do:** `GET /audit/queries` → **Try it out** → **Execute**.

    **Expected:** `403`, "Ehhez a művelethez nincs jogosultságod." ("You do not have permission
    for this operation.") Only the auditor and the admin can read the audit log.

[Next: Budaörsi Bea →](02-budaors-branch-manager.md)
