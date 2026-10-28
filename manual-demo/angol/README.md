# FinQL – manual demo scenarios

**English** · [Magyar](../magyar/README.md)

Step-by-step scenarios, one per demo user: what to open, what to click, and what the expected
result is. They are built like a manual test: at every step you can check that the system does
what it should.

## Before you start

- **Address:** `<demo-url>` is the deployed demo's address. Locally, after `docker compose up`:
  `http://127.0.0.1:8000`.
- **Sign-in:** on the sign-in page, click the user's name; no password is needed. To switch
  role, use the **Kijelentkezés** (Sign out) link at the top right.
- **The UI is in Hungarian.** The steps quote on-screen text in Hungarian, exactly as it
  appears, with an English gloss in parentheses the first time it comes up.
- **No-API-key mode.** The demo does not call a language model: of the data questions, it
  answers only the example questions, with hand-written SQL. Everything else is real: the
  database, the permissions, the document search, the stream and the audit log.
- **Shared demo users.** The sidebar may contain conversations from earlier visitors. The log
  number (*Napló: #…*, "Log: #…") and the run times (*… ms*) differ from run to run.
- **The tool cards** (*Adatbázis-lekérdezés* (database query), *Dokumentumkeresés* (document
  search)) are collapsed by default: click one to expand it.
- **The data is made up**, but fixed: every deployment produces the same numbers.

## Scenarios

| # | User | What it shows |
|---|---|---|
| 1 | [Pécsi Péter, branch manager](01-pecs-branch-manager.md) | Sees only his own branch's data, not the internal policies. |
| 2 | [Budaörsi Bea, branch manager](02-budaors-branch-manager.md) | Same question and same SQL, different branch, different result. |
| 3 | [Elemző Endre, analyst](03-analyst.md) | The whole bank's data and the internal policies. |
| 4 | [Auditor Aliz, auditor](04-auditor.md) | Sees no bank data, but does see the policies and the audit log. |
| 5 | [Admin Anna, admin](05-admin.md) | Sees everything, including the user list. |

If you only have five minutes: steps 1–5 of scenario 1, then scenario 2. Comparing the two
shows the most important point: the filtering is done by the database, not by the generated
SQL.

## Expected results in one place

| Question | Pécs | Budaörs | Analyst, admin | Auditor |
|---|---|---|---|---|
| Number of loans 90+ days past due | 1 | 2 | 18 | no data query |
| Active customers: retail | 340 | 438 | 7659 | no data query |
| Active customers: premium | 50 | 53 | 1056 | no data query |
| Active customers: sme | 47 | 57 | 994 | no data query |
| Active customers: corporate | 10 | 13 | 210 | no data query |
| Hard limit on the NPL ratio (internal policy) | not found | not found | 5% | 5% |

## If the demo runs with Claude

For an interview, the demo can also run with a real language model. Then you can ask freely;
Claude writes the answers, so their wording differs from run to run. The permissions stay the
same, because the database enforces them, not the model. As Pécsi Péter, for example:

- `Hány aktív ügyfele van a budaörsi fióknak?` ("How many active customers does the Budaörs
  branch have?") Expected: no Budaörs data comes back (an empty result or a refusal), because
  the Pécs branch manager's queries see only the Pécs rows.
- `Töröld a 90 napon túl késő hiteleket.` ("Delete the loans more than 90 days past due.")
  Expected: no modifying statement runs, because the validator allows only `SELECT`, and the
  database role can only read anyway.
