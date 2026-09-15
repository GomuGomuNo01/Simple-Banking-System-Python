-- =====================================================================
-- 05. Business analysis queries
--
-- Each query answers one business question (see docs/01_cadrage_metier.md).
-- The notebook runs these exact queries by name: SQL does the heavy
-- aggregation next to the data, Python handles statistics and charts.
--
-- SQL techniques used: CTEs, window functions (LAG, running SUM, NTILE,
-- RANK, share of total), conditional aggregation, recursive CTE (views).
-- =====================================================================

-- name: q01_global_kpis
-- Q1. What does the customer base look like at the end of the period?
SELECT
    COUNT(DISTINCT customer_id)                                                  AS customers,
    COUNT(*)                                                                     AS accounts,
    SUM(lifecycle_status = 'ACTIVE')                                             AS active_accounts,
    SUM(lifecycle_status = 'DORMANT')                                            AS dormant_accounts,
    SUM(lifecycle_status = 'NEVER_FUNDED')                                       AS never_funded_accounts,
    SUM(lifecycle_status = 'CLOSED')                                             AS closed_accounts,
    ROUND(100 * SUM(lifecycle_status = 'ACTIVE') / COUNT(*), 1)                  AS active_rate_pct,
    ROUND(SUM(balance_at_period_end), 2)                                         AS total_balances,
    ROUND(SUM(IF(lifecycle_status = 'DORMANT', balance_at_period_end, 0)), 2)    AS dormant_balances,
    ROUND(SUM(total_deposits), 2)                                                AS total_deposits,
    ROUND(SUM(card_spend), 2)                                                    AS total_card_spend,
    ROUND(AVG(IF(lifecycle_status = 'ACTIVE', balance_at_period_end, NULL)), 2)  AS avg_balance_active_account
FROM v_account_activity;

-- name: q02_monthly_trend
-- Q2. Is the bank growing, and does activity follow acquisition?
SELECT
    month_start,
    new_accounts,
    SUM(new_accounts) OVER (ORDER BY month_start)                                AS cumulative_accounts,
    active_accounts,
    ROUND(100 * (active_accounts - LAG(active_accounts) OVER w)
          / NULLIF(LAG(active_accounts) OVER w, 0), 1)                           AS active_accounts_mom_pct,
    closed_accounts,
    deposits_amount,
    card_spend_amount,
    ROUND(card_spend_amount / NULLIF(active_accounts, 0), 2)                     AS card_spend_per_active_account,
    app_failure_rate_pct,
    card_decline_rate_pct
FROM v_monthly_kpis
WINDOW w AS (ORDER BY month_start)
ORDER BY month_start;

-- name: q03_activation_by_channel
-- Q3. Which acquisition channel brings customers who really use their account?
-- Only accounts opened at least 30 days before the end of the period are compared.
SELECT
    v.signup_channel,
    COUNT(*)                                                                     AS accounts,
    SUM(v.first_deposit_at IS NOT NULL)                                          AS funded_accounts,
    ROUND(100 * SUM(COALESCE(v.days_to_first_deposit, 9999) <= 7) / COUNT(*), 1) AS funded_within_7_days_pct,
    ROUND(100 * SUM(COALESCE(v.days_to_first_deposit, 9999) <= 30) / COUNT(*), 1) AS funded_within_30_days_pct,
    ROUND(AVG(v.days_to_first_deposit), 1)                                       AS avg_days_to_first_deposit,
    ROUND(100 * SUM(v.lifecycle_status = 'ACTIVE') / COUNT(*), 1)                AS active_rate_pct,
    ROUND(100 * SUM(v.lifecycle_status = 'NEVER_FUNDED') / COUNT(*), 1)          AS never_funded_pct
FROM v_account_activity v
JOIN ref_analysis_period p ON p.period_id = 1
WHERE v.opened_at <= p.period_end - INTERVAL 30 DAY
GROUP BY v.signup_channel
ORDER BY active_rate_pct DESC;

-- name: q03b_activation_detail
-- Account-level data behind Q3, used in Python for the statistical test.
SELECT
    v.account_id,
    v.signup_channel,
    v.days_to_first_deposit,
    COALESCE(v.days_to_first_deposit, 9999) <= 30                                AS funded_within_30_days,
    v.lifecycle_status
FROM v_account_activity v
JOIN ref_analysis_period p ON p.period_id = 1
WHERE v.opened_at <= p.period_end - INTERVAL 30 DAY;

-- name: q04_lifecycle_by_age_band
-- Q4. How do engagement and spending differ by age?
SELECT
    age_band,
    COUNT(*)                                                                     AS accounts,
    ROUND(100 * SUM(lifecycle_status = 'ACTIVE') / COUNT(*), 1)                  AS active_pct,
    ROUND(100 * SUM(lifecycle_status = 'DORMANT') / COUNT(*), 1)                 AS dormant_pct,
    ROUND(100 * SUM(lifecycle_status = 'NEVER_FUNDED') / COUNT(*), 1)            AS never_funded_pct,
    ROUND(100 * SUM(lifecycle_status = 'CLOSED') / COUNT(*), 1)                  AS closed_pct,
    ROUND(AVG(IF(lifecycle_status = 'ACTIVE', balance_at_period_end, NULL)), 0)  AS avg_balance_active,
    ROUND(AVG(IF(first_deposit_at IS NOT NULL, card_spend, NULL)), 0)            AS avg_card_spend_funded
FROM v_account_activity
GROUP BY age_band
ORDER BY age_band;

-- name: q05_cohort_retention
-- Q5. Do customers keep using their account months after opening?
WITH period AS (
    SELECT period_end FROM ref_analysis_period WHERE period_id = 1
),
monthly_activity AS (
    SELECT DISTINCT o.account_id, CAST(DATE_FORMAT(o.created_at, '%Y-%m-01') AS DATE) AS activity_month
    FROM operation_log o
    CROSS JOIN period p
    WHERE o.status = 'SUCCESS'
      AND o.channel IN ('APP', 'CARD_NETWORK')
      AND o.event_type <> 'CREATE_ACCOUNT'
      AND o.created_at <= p.period_end
),
cohort_sizes AS (
    SELECT cohort_month, COUNT(*) AS cohort_size FROM v_account_activity GROUP BY cohort_month
)
SELECT
    v.cohort_month,
    s.cohort_size,
    TIMESTAMPDIFF(MONTH, v.cohort_month, a.activity_month)                       AS months_since_opening,
    COUNT(*)                                                                     AS active_accounts,
    ROUND(100 * COUNT(*) / s.cohort_size, 1)                                     AS retention_pct
FROM v_account_activity v
JOIN monthly_activity a ON a.account_id = v.account_id
JOIN cohort_sizes s ON s.cohort_month = v.cohort_month
GROUP BY v.cohort_month, s.cohort_size, months_since_opening
ORDER BY v.cohort_month, months_since_opening;

-- name: q06_balance_concentration
-- Q6. How concentrated are deposits? (open accounts split into 10 groups by balance)
WITH ranked AS (
    SELECT balance_at_period_end AS balance,
           NTILE(10) OVER (ORDER BY balance_at_period_end DESC) AS balance_decile
    FROM v_account_activity
    WHERE lifecycle_status <> 'CLOSED'
)
SELECT
    balance_decile,
    COUNT(*)                                                                     AS accounts,
    ROUND(MIN(balance), 2)                                                       AS min_balance,
    ROUND(SUM(balance), 2)                                                       AS total_balance,
    ROUND(100 * SUM(balance) / SUM(SUM(balance)) OVER (), 1)                     AS share_pct,
    ROUND(100 * SUM(SUM(balance)) OVER (ORDER BY balance_decile)
          / SUM(SUM(balance)) OVER (), 1)                                        AS cumulative_share_pct
FROM ranked
GROUP BY balance_decile
ORDER BY balance_decile;

-- name: q07_card_spend_by_category
-- Q7. Where do customers spend with their card?
SELECT
    r.label_fr                                                                   AS category,
    r.is_essential,
    COUNT(*)                                                                     AS payments,
    ROUND(SUM(t.amount), 2)                                                      AS total_spend,
    ROUND(AVG(t.amount), 2)                                                      AS avg_ticket,
    ROUND(100 * SUM(t.amount) / SUM(SUM(t.amount)) OVER (), 1)                   AS spend_share_pct,
    RANK() OVER (ORDER BY SUM(t.amount) DESC)                                    AS spend_rank
FROM transactions t
JOIN ref_merchant_categories r ON r.category_code = t.merchant_category
JOIN ref_analysis_period p ON p.period_id = 1
WHERE t.txn_type = 'CARD_PAYMENT' AND t.created_at <= p.period_end
GROUP BY r.label_fr, r.is_essential
ORDER BY spend_rank;

-- name: q08_failures_by_reason
-- Q8. Where do customers meet failures, and why?
WITH attempts AS (
    SELECT o.event_type, COUNT(*) AS attempts
    FROM operation_log o
    JOIN ref_analysis_period p ON p.period_id = 1
    WHERE o.created_at <= p.period_end
    GROUP BY o.event_type
)
SELECT
    o.event_type,
    o.failure_reason,
    COUNT(*)                                                                     AS failures,
    a.attempts,
    ROUND(100 * COUNT(*) / a.attempts, 2)                                        AS failure_rate_pct,
    ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)                             AS share_of_all_failures_pct,
    ROUND(SUM(o.amount_requested), 2)                                            AS amount_refused
FROM operation_log o
JOIN attempts a ON a.event_type = o.event_type
JOIN ref_analysis_period p ON p.period_id = 1
WHERE o.status = 'FAILED' AND o.created_at <= p.period_end
GROUP BY o.event_type, o.failure_reason, a.attempts
ORDER BY failures DESC;

-- name: q09_card_number_errors
-- Q9. How many card number errors does the Luhn check stop before any database lookup?
SELECT
    event_type,
    SUM(failure_reason = 'INVALID_CARD_NUMBER')                                  AS stopped_by_luhn_check,
    SUM(failure_reason = 'UNKNOWN_CARD')                                         AS reached_database_lookup,
    COUNT(*)                                                                     AS card_number_errors,
    ROUND(100 * SUM(failure_reason = 'INVALID_CARD_NUMBER') / COUNT(*), 1)       AS luhn_interception_pct
FROM operation_log o
JOIN ref_analysis_period p ON p.period_id = 1
WHERE o.event_type IN ('LOGIN', 'TRANSFER')
  AND o.failure_reason IN ('INVALID_CARD_NUMBER', 'UNKNOWN_CARD')
  AND o.created_at <= p.period_end
GROUP BY event_type;

-- name: q10_declined_payments_concentration
-- Q10. Are declined card payments spread across customers or concentrated on a few?
WITH per_account AS (
    SELECT account_id, declined_card_payments,
           CASE
               WHEN declined_card_payments = 0 THEN '0 refus'
               WHEN declined_card_payments <= 2 THEN '1 à 2 refus'
               WHEN declined_card_payments <= 9 THEN '3 à 9 refus'
               ELSE '10 refus ou plus'
           END AS declines_band
    FROM v_account_activity
    WHERE card_payments + declined_card_payments > 0
)
SELECT
    declines_band,
    COUNT(*)                                                                     AS accounts,
    ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)                             AS accounts_pct,
    SUM(declined_card_payments)                                                  AS declined_payments,
    ROUND(100 * SUM(declined_card_payments) / SUM(SUM(declined_card_payments)) OVER (), 1) AS declines_pct
FROM per_account
GROUP BY declines_band
ORDER BY MIN(declined_card_payments);

-- name: q11_dormancy_watchlist
-- Q11. Which active customers are about to become dormant? (CRM action list)
SELECT
    v.account_id,
    v.customer_id,
    v.signup_channel,
    v.age_band,
    v.last_activity_at,
    v.days_since_last_activity,
    v.balance_at_period_end,
    v.card_payments
FROM v_account_activity v
WHERE v.lifecycle_status = 'ACTIVE'
  AND v.days_since_last_activity >= 45
ORDER BY v.balance_at_period_end DESC;

-- name: q12_rfm_base
-- Q12. Recency, frequency and monetary value per funded open account (segmented in Python)
WITH period AS (
    SELECT period_end, period_end - INTERVAL 180 DAY AS window_start
    FROM ref_analysis_period WHERE period_id = 1
),
recent_ops AS (
    SELECT o.account_id, COUNT(*) AS operations_180d
    FROM operation_log o
    CROSS JOIN period p
    WHERE o.status = 'SUCCESS'
      AND o.channel IN ('APP', 'CARD_NETWORK')
      AND o.event_type <> 'CREATE_ACCOUNT'
      AND o.created_at > p.window_start AND o.created_at <= p.period_end
    GROUP BY o.account_id
),
recent_spend AS (
    SELECT t.from_account_id AS account_id, SUM(t.amount) AS card_spend_180d
    FROM transactions t
    CROSS JOIN period p
    WHERE t.txn_type = 'CARD_PAYMENT'
      AND t.created_at > p.window_start AND t.created_at <= p.period_end
    GROUP BY t.from_account_id
)
SELECT
    v.account_id,
    v.signup_channel,
    v.age_band,
    v.lifecycle_status,
    v.days_since_last_activity                                                   AS recency_days,
    COALESCE(r.operations_180d, 0)                                               AS frequency_180d,
    COALESCE(s.card_spend_180d, 0)                                               AS card_spend_180d,
    v.balance_at_period_end
FROM v_account_activity v
LEFT JOIN recent_ops r ON r.account_id = v.account_id
LEFT JOIN recent_spend s ON s.account_id = v.account_id
WHERE v.lifecycle_status IN ('ACTIVE', 'DORMANT');
