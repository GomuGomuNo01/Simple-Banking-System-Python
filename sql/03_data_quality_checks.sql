-- =====================================================================
-- 03. Data quality checks
-- Run by the pipeline (results saved in reports/data_quality_report.md)
-- or query by query in the IDE. Each query starts with "-- name:".
--
-- Why? An analysis is only as reliable as its data. These checks are run
-- BEFORE any analysis, and their results are published with it.
-- =====================================================================

-- name: crm_profiling
-- What the cleaning step found and fixed in the CRM export.
SELECT 'Lignes brutes dans l''export CRM' AS indicator, COUNT(*) AS value FROM stg_customers_raw
UNION ALL
SELECT 'Identifiants clients distincts', COUNT(DISTINCT TRIM(crm_customer_id)) FROM stg_customers_raw
UNION ALL
SELECT 'Doublons écartés (anciennes versions ou copies)', COUNT(*) - COUNT(DISTINCT TRIM(crm_customer_id)) FROM stg_customers_raw
UNION ALL
SELECT 'Orthographes différentes du canal d''inscription', COUNT(DISTINCT signup_channel COLLATE utf8mb4_bin) FROM stg_customers_raw
UNION ALL
SELECT 'Dates de naissance au format JJ/MM/AAAA', SUM(TRIM(birth_date) REGEXP '^[0-9]{2}/') FROM stg_customers_raw
UNION ALL
SELECT 'Prénoms ou noms avec espaces ou casse incohérente',
       SUM(first_name COLLATE utf8mb4_bin <> CONCAT(UPPER(LEFT(TRIM(first_name), 1)), LOWER(SUBSTRING(TRIM(first_name), 2)))
           OR last_name COLLATE utf8mb4_bin <> CONCAT(UPPER(LEFT(TRIM(last_name), 1)), LOWER(SUBSTRING(TRIM(last_name), 2))))
FROM stg_customers_raw
UNION ALL
SELECT 'Emails non normalisés (majuscules ou espaces)', SUM(email COLLATE utf8mb4_bin <> LOWER(TRIM(email))) FROM stg_customers_raw
UNION ALL
SELECT 'Villes non normalisées ou alias', SUM(city COLLATE utf8mb4_bin NOT IN (SELECT DISTINCT city COLLATE utf8mb4_bin FROM customers WHERE city IS NOT NULL) OR city = '') FROM stg_customers_raw
UNION ALL
SELECT 'Clients retenus dans la table customers', COUNT(*) FROM customers
UNION ALL
SELECT 'Clients avec email invalide (valeur mise à NULL)', SUM(dq_flags LIKE '%INVALID_EMAIL%') FROM customers
UNION ALL
SELECT 'Clients sans date de naissance', SUM(dq_flags LIKE '%MISSING_BIRTH_DATE%') FROM customers
UNION ALL
SELECT 'Clients avec date de naissance aberrante (mise à NULL)', SUM(dq_flags LIKE '%IMPLAUSIBLE_BIRTH_DATE%') FROM customers
UNION ALL
SELECT 'Clients sans ville', SUM(dq_flags LIKE '%MISSING_CITY%') FROM customers;

-- name: integrity_checks
-- Every check must return 0 failing rows.
WITH RECURSIVE positions AS (
    SELECT 1 AS pos
    UNION ALL
    SELECT pos + 1 FROM positions WHERE pos < 16
),
card_digits AS (
    -- pos = 1 is the rightmost digit (the check digit)
    SELECT a.account_id, p.pos, CAST(SUBSTRING(a.card_number, 17 - p.pos, 1) AS UNSIGNED) AS digit
    FROM accounts a
    CROSS JOIN positions p
),
luhn AS (
    SELECT account_id,
           SUM(CASE WHEN pos % 2 = 0 THEN digit * 2 - IF(digit * 2 > 9, 9, 0) ELSE digit END) AS checksum
    FROM card_digits
    GROUP BY account_id
),
flows AS (
    SELECT account_id, SUM(delta) AS computed_balance
    FROM (
        SELECT to_account_id AS account_id, amount AS delta FROM transactions WHERE to_account_id IS NOT NULL
        UNION ALL
        SELECT from_account_id, -amount FROM transactions WHERE from_account_id IS NOT NULL
    ) AS movements
    GROUP BY account_id
)
SELECT 'Solde différent de la somme des transactions' AS check_name, COUNT(*) AS failing_rows
FROM accounts a
LEFT JOIN flows f ON f.account_id = a.account_id
WHERE a.balance <> COALESCE(f.computed_balance, 0)
UNION ALL
SELECT 'Numéro de carte invalide (algorithme de Luhn recalculé en SQL)', COUNT(*)
FROM luhn WHERE checksum % 10 <> 0
UNION ALL
SELECT 'Numéro de carte en double', COUNT(*) - COUNT(DISTINCT card_number)
FROM accounts
UNION ALL
SELECT 'Solde négatif', COUNT(*)
FROM accounts WHERE balance < 0
UNION ALL
SELECT 'Transaction liée à une opération échouée, d''un autre type ou d''un autre montant', COUNT(*)
FROM transactions t
JOIN operation_log o ON o.operation_id = t.operation_id
WHERE o.status <> 'SUCCESS' OR o.event_type <> t.txn_type OR o.amount_requested <> t.amount
UNION ALL
SELECT 'Opération monétaire réussie sans transaction', COUNT(*)
FROM operation_log o
LEFT JOIN transactions t ON t.operation_id = o.operation_id
WHERE o.status = 'SUCCESS'
  AND o.event_type IN ('DEPOSIT', 'WITHDRAWAL', 'TRANSFER', 'CARD_PAYMENT')
  AND t.transaction_id IS NULL
UNION ALL
SELECT 'Opération antérieure à l''ouverture du compte', COUNT(*)
FROM operation_log o
JOIN accounts a ON a.account_id = o.account_id
WHERE o.created_at < a.opened_at
UNION ALL
SELECT 'Opération réussie après la clôture du compte', COUNT(*)
FROM operation_log o
JOIN accounts a ON a.account_id = o.account_id
WHERE a.closed_at IS NOT NULL AND o.status = 'SUCCESS' AND o.created_at > a.closed_at
UNION ALL
SELECT 'Virement reçu par un compte clôturé', COUNT(*)
FROM transactions t
JOIN accounts a ON a.account_id = t.to_account_id
WHERE a.closed_at IS NOT NULL AND t.created_at > a.closed_at
UNION ALL
SELECT 'Compte clôturé avec un solde restant', COUNT(*)
FROM accounts WHERE status = 'CLOSED' AND balance <> 0;
