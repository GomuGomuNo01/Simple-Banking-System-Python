-- =====================================================================
-- 06. Star schema export for Power BI
--
-- Why a star schema? Power BI is fastest and simplest with one fact table
-- per business process (activity, operations, card spend, retention)
-- surrounded by shared dimensions (calendar, channel, account).
-- The aggregation is done here, in SQL, from the analytics views, so the
-- dashboard uses exactly the same definitions as the notebook.
-- Run by: python -m sbs_bank.pipeline powerbi
-- =====================================================================

-- name: pbi_dim_account
SELECT
    v.account_id,
    v.customer_id,
    v.signup_channel,
    v.age_band,
    COALESCE(v.city, 'Non renseignée')                                  AS city,
    v.cohort_month,
    DATE(v.opened_at)                                                   AS opened_date,
    v.lifecycle_status,
    v.days_to_first_deposit,
    COALESCE(v.days_to_first_deposit, 9999) <= 7                        AS funded_within_7_days,
    COALESCE(v.days_to_first_deposit, 9999) <= 30                       AS funded_within_30_days,
    v.opened_at <= p.period_end - INTERVAL 30 DAY                       AS activation_eligible,
    v.days_since_last_activity,
    v.balance_at_period_end,
    v.card_spend,
    v.card_payments,
    v.declined_card_payments
FROM v_account_activity v
JOIN ref_analysis_period p ON p.period_id = 1;

-- name: pbi_fact_account_month
-- One row per account and month with at least one operation.
WITH period AS (
    SELECT period_end FROM ref_analysis_period WHERE period_id = 1
),
ops AS (
    SELECT
        o.account_id,
        CAST(DATE_FORMAT(o.created_at, '%Y-%m-01') AS DATE)                           AS month_start,
        MAX(o.status = 'SUCCESS' AND o.channel IN ('APP', 'CARD_NETWORK')
            AND o.event_type <> 'CREATE_ACCOUNT')                                     AS is_customer_active,
        SUM(o.status = 'SUCCESS' AND o.channel IN ('APP', 'CARD_NETWORK')
            AND o.event_type <> 'CREATE_ACCOUNT')                                     AS customer_operations,
        SUM(o.event_type = 'CARD_PAYMENT' AND o.status = 'SUCCESS')                   AS card_payments,
        SUM(o.event_type = 'CARD_PAYMENT' AND o.status = 'FAILED')                    AS declined_card_payments
    FROM operation_log o
    CROSS JOIN period p
    WHERE o.account_id IS NOT NULL AND o.created_at <= p.period_end
    GROUP BY o.account_id, month_start
),
money AS (
    SELECT account_id, month_start, SUM(card_spend) AS card_spend, SUM(deposits) AS deposits
    FROM (
        SELECT t.from_account_id AS account_id, CAST(DATE_FORMAT(t.created_at, '%Y-%m-01') AS DATE) AS month_start,
               t.amount AS card_spend, 0 AS deposits
        FROM transactions t CROSS JOIN period p
        WHERE t.txn_type = 'CARD_PAYMENT' AND t.created_at <= p.period_end
        UNION ALL
        SELECT t.to_account_id, CAST(DATE_FORMAT(t.created_at, '%Y-%m-01') AS DATE), 0, t.amount
        FROM transactions t CROSS JOIN period p
        WHERE t.txn_type = 'DEPOSIT' AND t.created_at <= p.period_end
    ) AS flows
    GROUP BY account_id, month_start
)
SELECT
    o.account_id,
    o.month_start,
    o.is_customer_active,
    o.customer_operations,
    o.card_payments,
    o.declined_card_payments,
    COALESCE(m.card_spend, 0)  AS card_spend,
    COALESCE(m.deposits, 0)    AS deposits
FROM ops o
LEFT JOIN money m ON m.account_id = o.account_id AND m.month_start = o.month_start;

-- name: pbi_fact_operations
-- Attempts per month, channel, operation type, result and failure reason.
SELECT
    CAST(DATE_FORMAT(o.created_at, '%Y-%m-01') AS DATE)   AS month_start,
    COALESCE(c.signup_channel, 'UNKNOWN')                 AS signup_channel,
    o.event_type,
    o.status,
    COALESCE(o.failure_reason, 'NONE')                    AS failure_reason,
    COUNT(*)                                              AS attempts,
    COALESCE(SUM(o.amount_requested), 0)                  AS amount_requested
FROM operation_log o
JOIN ref_analysis_period p ON p.period_id = 1
LEFT JOIN accounts a ON a.account_id = o.account_id
LEFT JOIN customers c ON c.customer_id = a.customer_id
WHERE o.created_at <= p.period_end
GROUP BY month_start, signup_channel, o.event_type, o.status, failure_reason;

-- name: pbi_fact_card_spend
SELECT
    CAST(DATE_FORMAT(t.created_at, '%Y-%m-01') AS DATE)   AS month_start,
    c.signup_channel,
    r.label_fr                                            AS category,
    r.is_essential,
    COUNT(*)                                              AS payments,
    SUM(t.amount)                                         AS amount
FROM transactions t
JOIN ref_analysis_period p ON p.period_id = 1
JOIN accounts a ON a.account_id = t.from_account_id
JOIN customers c ON c.customer_id = a.customer_id
JOIN ref_merchant_categories r ON r.category_code = t.merchant_category
WHERE t.txn_type = 'CARD_PAYMENT' AND t.created_at <= p.period_end
GROUP BY month_start, c.signup_channel, r.label_fr, r.is_essential;

-- name: pbi_fact_retention
-- Cohort retention split by acquisition channel (additive: sums of active
-- accounts and cohort sizes can be combined across channels).
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
    SELECT cohort_month, signup_channel, COUNT(*) AS cohort_size
    FROM v_account_activity
    GROUP BY cohort_month, signup_channel
)
SELECT
    v.cohort_month,
    v.signup_channel,
    TIMESTAMPDIFF(MONTH, v.cohort_month, a.activity_month)   AS months_since_opening,
    COUNT(*)                                                 AS active_accounts,
    s.cohort_size
FROM v_account_activity v
JOIN monthly_activity a ON a.account_id = v.account_id
JOIN cohort_sizes s ON s.cohort_month = v.cohort_month AND s.signup_channel = v.signup_channel
GROUP BY v.cohort_month, v.signup_channel, months_since_opening, s.cohort_size;
