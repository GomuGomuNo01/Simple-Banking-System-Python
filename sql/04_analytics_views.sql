-- =====================================================================
-- 04. Analytics views
--
-- Why views? Business definitions (active account, dormant account,
-- activation...) are written ONCE in SQL and reused by every query, the
-- notebook and any BI tool. Everyone computes "active accounts" the same way.
--
-- Definitions
--   Customer activity : successful operation initiated by the customer
--                       (app or card payment), account creation excluded
--   Activation        : first successful deposit
--   ACTIVE            : activity during the last `dormancy_days` (90) days
--   DORMANT           : funded account without activity for 90+ days
--   NEVER_FUNDED      : open account that never received a deposit
--   CLOSED            : account closed before the end of the period
-- =====================================================================

-- ---------------------------------------------------------------------
-- One row per account: profile, activation, activity, money flows, status
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_account_activity AS
WITH period AS (
    SELECT period_start, period_end, dormancy_days FROM ref_analysis_period WHERE period_id = 1
),
ops AS (
    SELECT
        o.account_id,
        MIN(CASE WHEN o.event_type = 'DEPOSIT' AND o.status = 'SUCCESS' THEN o.created_at END) AS first_deposit_at,
        MAX(CASE WHEN o.status = 'SUCCESS' AND o.channel IN ('APP', 'CARD_NETWORK')
                  AND o.event_type <> 'CREATE_ACCOUNT' THEN o.created_at END)                 AS last_activity_at,
        SUM(o.event_type = 'LOGIN' AND o.status = 'SUCCESS')                                 AS logins,
        SUM(o.event_type = 'CARD_PAYMENT' AND o.status = 'SUCCESS')                          AS card_payments,
        SUM(o.event_type = 'CARD_PAYMENT' AND o.status = 'FAILED')                           AS declined_card_payments,
        SUM(o.status = 'FAILED')                                                             AS failed_operations
    FROM operation_log o
    CROSS JOIN period p
    WHERE o.account_id IS NOT NULL AND o.created_at <= p.period_end
    GROUP BY o.account_id
),
movements AS (
    SELECT t.to_account_id AS account_id, t.txn_type, t.amount AS amount_in, 0 AS amount_out
    FROM transactions t CROSS JOIN period p
    WHERE t.to_account_id IS NOT NULL AND t.created_at <= p.period_end
    UNION ALL
    SELECT t.from_account_id, t.txn_type, 0, t.amount
    FROM transactions t CROSS JOIN period p
    WHERE t.from_account_id IS NOT NULL AND t.created_at <= p.period_end
),
money AS (
    SELECT
        account_id,
        SUM(IF(txn_type = 'DEPOSIT', amount_in, 0))       AS total_deposits,
        SUM(IF(txn_type = 'TRANSFER', amount_in, 0))      AS transfers_received,
        SUM(IF(txn_type = 'TRANSFER', amount_out, 0))     AS transfers_sent,
        SUM(IF(txn_type = 'CARD_PAYMENT', amount_out, 0)) AS card_spend,
        SUM(IF(txn_type = 'WITHDRAWAL', amount_out, 0))   AS withdrawals,
        SUM(amount_in) - SUM(amount_out)                  AS balance_at_period_end
    FROM movements
    GROUP BY account_id
)
SELECT
    a.account_id,
    a.customer_id,
    c.signup_channel,
    c.city,
    TIMESTAMPDIFF(YEAR, c.birth_date, a.opened_at)                        AS age_at_opening,
    CASE
        WHEN c.birth_date IS NULL THEN 'Inconnu'
        WHEN TIMESTAMPDIFF(YEAR, c.birth_date, a.opened_at) < 25 THEN '18-24'
        WHEN TIMESTAMPDIFF(YEAR, c.birth_date, a.opened_at) < 35 THEN '25-34'
        WHEN TIMESTAMPDIFF(YEAR, c.birth_date, a.opened_at) < 45 THEN '35-44'
        WHEN TIMESTAMPDIFF(YEAR, c.birth_date, a.opened_at) < 55 THEN '45-54'
        ELSE '55+'
    END                                                                   AS age_band,
    a.opened_at,
    CAST(DATE_FORMAT(a.opened_at, '%Y-%m-01') AS DATE)                    AS cohort_month,
    IF(a.closed_at <= p.period_end, a.closed_at, NULL)                    AS closed_at,
    o.first_deposit_at,
    TIMESTAMPDIFF(DAY, a.opened_at, o.first_deposit_at)                   AS days_to_first_deposit,
    o.last_activity_at,
    TIMESTAMPDIFF(DAY, o.last_activity_at, p.period_end)                  AS days_since_last_activity,
    COALESCE(o.logins, 0)                                                 AS logins,
    COALESCE(o.card_payments, 0)                                          AS card_payments,
    COALESCE(o.declined_card_payments, 0)                                 AS declined_card_payments,
    COALESCE(o.failed_operations, 0)                                      AS failed_operations,
    COALESCE(m.total_deposits, 0)                                         AS total_deposits,
    COALESCE(m.transfers_received, 0)                                     AS transfers_received,
    COALESCE(m.transfers_sent, 0)                                         AS transfers_sent,
    COALESCE(m.card_spend, 0)                                             AS card_spend,
    COALESCE(m.withdrawals, 0)                                            AS withdrawals,
    COALESCE(m.balance_at_period_end, 0)                                  AS balance_at_period_end,
    CASE
        WHEN a.closed_at <= p.period_end THEN 'CLOSED'
        WHEN o.first_deposit_at IS NULL THEN 'NEVER_FUNDED'
        WHEN o.last_activity_at >= p.period_end - INTERVAL p.dormancy_days DAY THEN 'ACTIVE'
        ELSE 'DORMANT'
    END                                                                   AS lifecycle_status
FROM accounts a
JOIN customers c ON c.customer_id = a.customer_id
CROSS JOIN period p
LEFT JOIN ops o ON o.account_id = a.account_id
LEFT JOIN money m ON m.account_id = a.account_id
WHERE a.opened_at <= p.period_end;

-- ---------------------------------------------------------------------
-- One row per month: acquisition, activity, money flows, service quality
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_monthly_kpis AS
WITH RECURSIVE months AS (
    SELECT CAST(DATE_FORMAT(period_start, '%Y-%m-01') AS DATE) AS month_start, period_end
    FROM ref_analysis_period WHERE period_id = 1
    UNION ALL
    SELECT month_start + INTERVAL 1 MONTH, period_end
    FROM months
    WHERE month_start + INTERVAL 1 MONTH <= period_end
),
ops AS (
    SELECT
        CAST(DATE_FORMAT(o.created_at, '%Y-%m-01') AS DATE)                                  AS month_start,
        SUM(o.event_type = 'CREATE_ACCOUNT')                                                 AS new_accounts,
        SUM(o.event_type = 'CLOSE_ACCOUNT')                                                  AS closed_accounts,
        COUNT(DISTINCT CASE WHEN o.status = 'SUCCESS' AND o.channel IN ('APP', 'CARD_NETWORK')
                             AND o.event_type <> 'CREATE_ACCOUNT' THEN o.account_id END)     AS active_accounts,
        SUM(o.channel = 'APP' AND o.event_type IN ('LOGIN', 'DEPOSIT', 'WITHDRAWAL', 'TRANSFER')) AS app_attempts,
        SUM(o.channel = 'APP' AND o.event_type IN ('LOGIN', 'DEPOSIT', 'WITHDRAWAL', 'TRANSFER')
            AND o.status = 'FAILED')                                                         AS app_failures,
        SUM(o.event_type = 'CARD_PAYMENT')                                                   AS card_payment_attempts,
        SUM(o.event_type = 'CARD_PAYMENT' AND o.status = 'FAILED')                           AS declined_card_payments
    FROM operation_log o
    JOIN ref_analysis_period p ON p.period_id = 1
    WHERE o.created_at <= p.period_end
    GROUP BY month_start
),
money AS (
    SELECT
        CAST(DATE_FORMAT(t.created_at, '%Y-%m-01') AS DATE)   AS month_start,
        SUM(IF(t.txn_type = 'DEPOSIT', t.amount, 0))          AS deposits_amount,
        SUM(IF(t.txn_type = 'CARD_PAYMENT', t.amount, 0))     AS card_spend_amount,
        SUM(IF(t.txn_type = 'TRANSFER', t.amount, 0))         AS transfers_amount,
        SUM(IF(t.txn_type = 'WITHDRAWAL', t.amount, 0))       AS withdrawals_amount
    FROM transactions t
    JOIN ref_analysis_period p ON p.period_id = 1
    WHERE t.created_at <= p.period_end
    GROUP BY month_start
)
SELECT
    m.month_start,
    COALESCE(o.new_accounts, 0)                                                   AS new_accounts,
    COALESCE(o.closed_accounts, 0)                                                AS closed_accounts,
    COALESCE(o.active_accounts, 0)                                                AS active_accounts,
    COALESCE(mo.deposits_amount, 0)                                               AS deposits_amount,
    COALESCE(mo.card_spend_amount, 0)                                             AS card_spend_amount,
    COALESCE(mo.transfers_amount, 0)                                              AS transfers_amount,
    COALESCE(mo.withdrawals_amount, 0)                                            AS withdrawals_amount,
    COALESCE(o.card_payment_attempts, 0)                                          AS card_payment_attempts,
    ROUND(100 * o.app_failures / NULLIF(o.app_attempts, 0), 2)                    AS app_failure_rate_pct,
    ROUND(100 * o.declined_card_payments / NULLIF(o.card_payment_attempts, 0), 2) AS card_decline_rate_pct
FROM months m
LEFT JOIN ops o ON o.month_start = m.month_start
LEFT JOIN money mo ON mo.month_start = m.month_start;
