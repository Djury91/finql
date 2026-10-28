# 2. Budaörsi Bea, branch manager

[← Scenarios](README.md)

**What it shows:** the same question runs the same SQL as for Pécsi Péter, but gives a
different result, because Budaörsi Bea is the manager of the Budaörs branch (BUO01). The
difference comes from the database's permission rules, not from the SQL.

## Sign in

1. **Do:** on `<demo-url>` (if you are signed in, first click **Kijelentkezés** (Sign out) at
   the top right), click the **Budaörsi Bea – fiókvezető (BUO01)** (branch manager) button.

   **Expected:** "Budaörsi Bea" and the *fiókvezető* (branch manager) label at the top right.

## Same question, different branch

2. **Do:** click the example question **Hány 90+ napos késedelmes hitelünk van, és mi a teendő a
   szabályzat szerint?** ("How many loans are 90+ days past due, and what does the policy say
   to do?"), then expand the *Adatbázis-lekérdezés* (database query) card.

   **Expected:**
   - the SQL is identical, letter for letter, to the one in scenario 1, step 4;
   - in the table `loans` = **2** (in Pécs it was 1);
   - in the answer: "Az adatbázis szerint (csak a felhasználó saját fiókja (branch_id = 2)):
     loans = 2." ("According to the database (only the user's own branch (branch_id = 2)):
     loans = 2.")
3. **Do:** **Új beszélgetés** (New conversation), then the example question **Hány aktív
   ügyfelünk van szegmensenként?** ("How many active customers do we have per segment?").
   Expand the *Adatbázis-lekérdezés* card.

   **Expected:** the Budaörs customers, with numbers different from Pécs:

   | segment | customers |
   |---|---|
   | retail | 438 |
   | sme | 57 |
   | premium | 53 |
   | corporate | 13 |

## Another user's conversations

4. **Do:** look at the conversation list on the left.

   **Expected:** it contains only Budaörsi Bea's conversations; Pécsi Péter's questions do not
   show, even if you asked them a moment ago in the same browser.

[← Previous: Pécsi Péter](01-pecs-branch-manager.md) · [Next: Elemző Endre →](03-analyst.md)
