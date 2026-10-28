# 3. Elemző Endre, analyst

[← Scenarios](README.md)

**What it shows:** the analyst sees the whole bank's data and can also read the internal
policies. The same questions as for the branch managers, with bank-wide results.

## Sign in

1. **Do:** on `<demo-url>` (if you are signed in, first click **Kijelentkezés** (Sign out)),
   click the **Elemző Endre – elemző** (analyst) button.

   **Expected:** "Elemző Endre" and the *elemző* (analyst) label at the top right.

## The whole bank

2. **Do:** click the example question **Hány 90+ napos késedelmes hitelünk van, és mi a teendő a
   szabályzat szerint?** ("How many loans are 90+ days past due, and what does the policy say
   to do?"), then expand the *Adatbázis-lekérdezés* (database query) card.

   **Expected:**
   - the same SQL as for the branch managers;
   - `loans` = **18** (Pécs: 1, Budaörs: 2);
   - in the answer: "Az adatbázis szerint (a bank összes fiókja): loans = 18." ("According to
     the database (all branches of the bank): loans = 18.")
3. **Do:** **Új beszélgetés** (New conversation), then the example question **Hány aktív
   ügyfelünk van szegmensenként?** ("How many active customers do we have per segment?").
   Expand the *Adatbázis-lekérdezés* card.

   **Expected:**

   | segment | customers |
   |---|---|
   | retail | 7659 |
   | premium | 1056 |
   | sme | 994 |
   | corporate | 210 |

## A complex query

4. **Do:** **Új beszélgetés**, type exactly:
   `Melyik fiókban nőtt legjobban a kártyás költés negyedéves összevetésben?`
   ("Which branch had the largest quarter-over-quarter growth in card spending?")
   (This is one of the example questions from the project plan, so it has SQL even without a
   key.) Expand the *Adatbázis-lekérdezés* card.

   **Expected:** SQL that computes the result with a `WITH` clause and a `LAG` window function,
   and this result (*fiók* = branch; the UI uses a decimal comma, so 58,5 means 58.5):

   | branch | quarter | growth_pct |
   |---|---|---|
   | Debreceni fiók | 2026-07-01 | 58,5 |
   | Békéscsabai fiók | 2026-07-01 | 21,9 |
   | Kaposvári fiók | 2026-07-01 | 15,3 |
   | Zalaegerszegi fiók | 2026-07-01 | 14 |
   | Kecskeméti fiók | 2026-07-01 | 13,5 |

   Below it: "5 sor, a LIMIT levágta: lehet több is." ("5 rows, cut off by the LIMIT: there may
   be more.")
5. **Do:** look at the *Dokumentumkeresés* (document search) card.

   **Expected:** the first hit is the internal policy *Kártyacsalás-megelőzés – monitoring
   szabályok* (Card fraud prevention – monitoring rules). The branch managers would not get it.

## Internal policy: the analyst finds it

6. **Do:** **Új beszélgetés**, type `Mekkora az NPL-ráta kemény limitje?` ("What is the hard
   limit on the NPL ratio?")

   **Expected:** all three hits come from the internal policy *Hitelportfólió-limitek és
   kockázati étvágy 2026* (Loan portfolio limits and risk appetite 2026); the first is the
   *Kockázati étvágy* (Risk appetite) section. The answer quotes: "NPL-ráta (90 napon túl késő
   hitelek tőketartozásának aránya): célérték 3% alatt, figyelmeztető szint 4%, kemény limit
   5%." ("NPL ratio (share of outstanding principal on loans more than 90 days past due):
   target below 3%, warning level 4%, hard limit 5%.") Pécsi Péter did not get this document
   for the same question (scenario 1, step 9).

## API (optional)

7. **Do:** on `<demo-url>/docs`, **Authorize** with `elemzo@minta-bank.example` and the shared
   password. Then `POST /query`, **Try it out**, request body:
   `{"question": "Hány aktív ügyfelünk van szegmensenként?"}`, then **Execute**.

   **Expected:** `200`, `"status": "ok"`, the executed SQL, and the same four rows as in step 3.
   The `explanation`: "Kézzel írt minta-SQL (ál-LLM, API-kulcs nélküli mód)." ("Hand-written
   sample SQL (fake LLM, no-API-key mode).")

[← Previous: Budaörsi Bea](02-budaors-branch-manager.md) · [Next: Auditor Aliz →](04-auditor.md)
