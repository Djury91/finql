# 4. Auditor Aliz, auditor

[← Scenarios](README.md)

**What it shows:** the auditor sees no bank data, so she gets no database tool either. She can
read the policies, the internal ones too, and she checks the audit log: who asked what, which
SQL ran, and whether anyone has altered the log afterwards.

## Sign in

1. **Do:** on `<demo-url>` (if you are signed in, first click **Kijelentkezés** (Sign out)),
   click the **Auditor Aliz – auditor** button.

   **Expected:** "Auditor Aliz" and the *auditor* label at the top right.

## Data question: no database tool

2. **Do:** click the example question **Hány 90+ napos késedelmes hitelünk van, és mi a teendő a
   szabályzat szerint?** ("How many loans are 90+ days past due, and what does the policy say
   to do?").

   **Expected:** there is only a *Dokumentumkeresés* (document search) card, no
   *Adatbázis-lekérdezés* (database query) card. The answer has no "Az adatbázis szerint…"
   ("According to the database…") line, only the quote from the *Követeléskezelési szabályzat*
   (Collections policy). The same question gave the branch managers and the analyst a number as
   well.

## Internal policy

3. **Do:** **Új beszélgetés** (New conversation), type `Mekkora az NPL-ráta kemény limitje?`
   ("What is the hard limit on the NPL ratio?")

   **Expected:** the hits come from the internal policy *Hitelportfólió-limitek és kockázati
   étvágy 2026* (Loan portfolio limits and risk appetite 2026), and the answer quotes: "…
   kemény limit 5%." ("… hard limit 5%.")

## Audit log (API)

The UI does not show the audit log; it is available through the API.

4. **Do:** open `<demo-url>/docs`, **Authorize** with `auditor@minta-bank.example` and the
   shared password shown at the bottom of the sign-in page.
5. **Do:** `POST /query`, **Try it out**, request body:
   `{"question": "Hány aktív ügyfelünk van szegmensenként?"}`, **Execute**.

   **Expected:** `403`, "Ehhez a művelethez nincs jogosultságod." ("You do not have permission
   for this operation.") The auditor cannot query bank data through the API either.
6. **Do:** `GET /audit/queries` → **Try it out** → **Execute**.

   **Expected:** `200`, every user's queries, newest first. Each row includes, among others:
   `user_id`, `scope` (`branch` for the branch managers, `all` for the analyst and the admin),
   `branch_id`, `question`, `generated_sql`, `executed_sql`, `status`. If you went through
   scenarios 1–3 beforehand, your questions are here.
7. **Do:** `GET /audit/chain` → **Try it out** → **Execute**.

   **Expected:** `200`, two items: `"log": "query_log"` and `"log": "answer_log"`, both with
   `"intact": true` and `"broken_at": null`. `checked` tells how many rows were checked;
   `head_hash` is the hash of the last link in the chain. A log row altered, deleted or inserted
   afterwards would give `"intact": false` here, with the number of the bad row.

[← Previous: Elemző Endre](03-analyst.md) · [Next: Admin Anna →](05-admin.md)
