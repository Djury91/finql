-- Sorszintű jogosultság (RLS) a fiókhoz kötött banki táblákon.
--
-- A policy-k a finql_analytics szerepkörre szólnak: ő az analytics nézetek tulajdonosa, a nézetek
-- az ő nevében olvassák a bank táblákat. Más szerepkörre nincs policy, így az RLS-t bekapcsolva
-- alapból semmit sem látnak. A táblatulajdonos (finql_owner: migráció, seed) nem érintett.
--
-- Miért (SELECT app_ctx.…())? Skalár részlekérdezésként (InitPlan) a függvény egyszer fut le,
-- nem soronként, és a tervező paraméterként kezeli. Így a sorszám-becslés használható marad: a
-- beágyazott formánál „minden fiók” módban ~200-szoros alulbecslés és nested loop lett a vége.

-- Törzsadatokon (fiókok, termékek, kereskedők, árfolyamok, üzleti nap) nincs RLS: ezek nem
-- ügyfélhez kötöttek, egy fiókvezető is láthatja őket.

ALTER TABLE bank.customers         ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank.accounts          ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank.cards             ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank.loans             ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank.loan_installments ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank.transactions      ENABLE ROW LEVEL SECURITY;

CREATE POLICY branch_scope ON bank.customers
    FOR SELECT TO finql_analytics
    USING ((SELECT app_ctx.all_branches()) OR home_branch_id = (SELECT app_ctx.branch_id()));

CREATE POLICY branch_scope ON bank.accounts
    FOR SELECT TO finql_analytics
    USING ((SELECT app_ctx.all_branches()) OR branch_id = (SELECT app_ctx.branch_id()));

-- A tranzakciónál JOIN nélkül szűrünk: a denormalizált branch_id-t az összetett FK
-- tartja szinkronban a számlával (db/bank/010_transactions.sql).
CREATE POLICY branch_scope ON bank.transactions
    FOR SELECT TO finql_analytics
    USING ((SELECT app_ctx.all_branches()) OR branch_id = (SELECT app_ctx.branch_id()));

CREATE POLICY branch_scope ON bank.cards
    FOR SELECT TO finql_analytics
    USING (
        (SELECT app_ctx.all_branches())
        OR EXISTS (
            SELECT FROM bank.accounts a
            WHERE a.account_id = cards.account_id AND a.branch_id = (SELECT app_ctx.branch_id())
        )
    );

CREATE POLICY branch_scope ON bank.loans
    FOR SELECT TO finql_analytics
    USING (
        (SELECT app_ctx.all_branches())
        OR EXISTS (
            SELECT FROM bank.accounts a
            WHERE a.account_id = loans.account_id AND a.branch_id = (SELECT app_ctx.branch_id())
        )
    );

CREATE POLICY branch_scope ON bank.loan_installments
    FOR SELECT TO finql_analytics
    USING (
        (SELECT app_ctx.all_branches())
        OR EXISTS (
            SELECT FROM bank.loans l JOIN bank.accounts a USING (account_id)
            WHERE l.loan_id = loan_installments.loan_id AND a.branch_id = (SELECT app_ctx.branch_id())
        )
    );
