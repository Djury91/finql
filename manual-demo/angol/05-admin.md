# 5. Admin Anna, admin

[← Scenarios](README.md)

**What it shows:** the admin sees the whole bank's data, can read every policy, can check the
audit log, and is the only one who can see the user list.

## Sign in

1. **Do:** on `<demo-url>` (if you are signed in, first click **Kijelentkezés** (Sign out)),
   click the **Admin Anna – admin** button.

   **Expected:** "Admin Anna" and the *admin* label at the top right.

## Data question

2. **Do:** click the example question **Hány 90+ napos késedelmes hitelünk van, és mi a teendő a
   szabályzat szerint?** ("How many loans are 90+ days past due, and what does the policy say
   to do?"), then expand the *Adatbázis-lekérdezés* (database query) card.

   **Expected:** `loans` = **18**, as for the analyst; the answer says "(a bank összes fiókja)"
   ("(all branches of the bank)").

## Users and audit log (API)

3. **Do:** on `<demo-url>/docs`, **Authorize** with `admin@minta-bank.example` and the shared
   password.
4. **Do:** `GET /auth/users` → **Try it out** → **Execute**.

   **Expected:** `200`, five users: `admin@`, `auditor@`, `budaors@`, `elemzo@` and
   `pecs@minta-bank.example`, with their roles (`admin`, `auditor`, `branch_manager`,
   `analyst`). The response contains no password or password hash.
5. **Do:** the same as Pécsi Péter (**Logout**, then **Authorize** with the `pecs@` address).

   **Expected:** `403`, "Ehhez a művelethez nincs jogosultságod." ("You do not have permission
   for this operation.")
6. **Do:** as admin, `GET /audit/chain`.

   **Expected:** `200`, both logs `"intact": true`, as for the auditor.

[← Previous: Auditor Aliz](04-auditor.md) · [Back to the scenarios](README.md)
