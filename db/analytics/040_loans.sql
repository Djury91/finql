-- Hitelek előre kiszámolt késedelmi mutatókkal, hogy az LLM-nek ne kelljen kitalálnia az üzleti logikát.
-- A „ma” az üzleti nap (bank.business_day), nem a current_date.

CREATE VIEW analytics.loans AS
SELECT l.loan_id,
       l.account_id,
       a.customer_id,
       a.branch_id,
       p.product_type,
       p.name               AS product_name,
       l.principal,
       l.interest_rate,
       l.term_months,
       l.start_date,
       l.status,
       i.remaining_amount,
       i.overdue_amount,
       coalesce(bd.business_date - i.first_overdue_date, 0) AS days_past_due,
       CASE
           WHEN i.first_overdue_date IS NULL THEN '0'
           WHEN bd.business_date - i.first_overdue_date <= 30 THEN '1-30'
           WHEN bd.business_date - i.first_overdue_date <= 60 THEN '31-60'
           WHEN bd.business_date - i.first_overdue_date <= 90 THEN '61-90'
           ELSE '90+'
       END AS dpd_bucket
FROM bank.loans l
JOIN bank.accounts a USING (account_id)
JOIN bank.products p ON p.product_id = a.product_id
CROSS JOIN bank.business_day bd
-- Hitelenként a saját részletei (PK-index): fiókszintű szűrésnél csak a látható hiteleké fut le.
CROSS JOIN LATERAL (
    SELECT sum(li.amount_due - li.amount_paid) AS remaining_amount,
           coalesce(sum(li.amount_due - li.amount_paid)
                        FILTER (WHERE li.due_date <= bd.business_date), 0) AS overdue_amount,
           min(li.due_date)
               FILTER (WHERE li.due_date <= bd.business_date
                         AND li.amount_paid < li.amount_due) AS first_overdue_date
    FROM bank.loan_installments li
    WHERE li.loan_id = l.loan_id
) i;
