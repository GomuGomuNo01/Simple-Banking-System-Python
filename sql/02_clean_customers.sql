-- =====================================================================
-- 02. Customer data preparation: stg_customers_raw -> customers
--
-- Problems found while profiling the CRM export (see reports/data_quality_report.md)
--   1. Same customer exported several times (older versions, exact copies)
--   2. Names and cities with inconsistent case and extra spaces
--   3. Emails in upper case, with spaces, or invalid (" at " instead of "@")
--   4. Birth dates in two formats (YYYY-MM-DD and DD/MM/YYYY), missing or implausible
--   5. Signup channel written in 13 different ways
--   6. City aliases (St-Etienne, Saint Etienne...)
--
-- Why SQL here? The data already sits in the database: set-based
-- transformations are fast, auditable and re-runnable without moving data.
-- Rule: nothing is silently deleted. Unusable values become NULL and the
-- reason is kept in dq_flags.
-- =====================================================================

DELETE FROM customers;

INSERT INTO customers (customer_id, first_name, last_name, email, birth_date, city,
                       signup_channel, crm_updated_at, dq_flags)
WITH normalized AS (
    SELECT
        CAST(TRIM(crm_customer_id) AS UNSIGNED)                                   AS customer_id,
        CONCAT(UPPER(LEFT(TRIM(first_name), 1)), LOWER(SUBSTRING(TRIM(first_name), 2))) AS first_name,
        CONCAT(UPPER(LEFT(TRIM(last_name), 1)), LOWER(SUBSTRING(TRIM(last_name), 2)))   AS last_name,
        LOWER(TRIM(email))                                                       AS email_clean,
        TRIM(birth_date)                                                         AS birth_raw,
        CASE
            WHEN TRIM(birth_date) REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN STR_TO_DATE(TRIM(birth_date), '%Y-%m-%d')
            WHEN TRIM(birth_date) REGEXP '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN STR_TO_DATE(TRIM(birth_date), '%d/%m/%Y')
        END                                                                      AS birth_parsed,
        CASE
            WHEN TRIM(city) = '' OR city IS NULL THEN NULL
            WHEN LOWER(TRIM(city)) IN ('st-etienne', 'st etienne', 'saint etienne', 'saint-etienne') THEN 'Saint-Étienne'
            ELSE CONCAT(UPPER(LEFT(TRIM(city), 1)), LOWER(SUBSTRING(TRIM(city), 2)))
        END                                                                      AS city,
        CASE
            WHEN LOWER(TRIM(signup_channel)) IN ('mobile', 'app mobile', 'mobile_app') THEN 'MOBILE'
            WHEN LOWER(TRIM(signup_channel)) IN ('web', 'site web') THEN 'WEB'
            WHEN LOWER(TRIM(signup_channel)) IN ('partner', 'partenaire') THEN 'PARTNER'
        END                                                                      AS signup_channel,
        STR_TO_DATE(TRIM(updated_at), '%Y-%m-%d %H:%i:%s')                       AS crm_updated_at
    FROM stg_customers_raw
),
validated AS (
    SELECT
        n.*,
        n.email_clean REGEXP '^[a-z0-9._%+-]+@[a-z0-9.-]+\\.[a-z]{2,}$'          AS email_is_valid,
        n.birth_parsed IS NOT NULL
            AND n.birth_parsed >= '1920-01-01'
            AND TIMESTAMPDIFF(YEAR, n.birth_parsed, n.crm_updated_at) >= 18      AS birth_is_plausible
    FROM normalized n
),
deduplicated AS (
    -- Keep the most recent version of each customer
    SELECT v.*, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY crm_updated_at DESC) AS version_rank
    FROM validated v
)
SELECT
    customer_id,
    first_name,
    last_name,
    IF(email_is_valid, email_clean, NULL),
    IF(birth_is_plausible, birth_parsed, NULL),
    city,
    signup_channel,
    crm_updated_at,
    NULLIF(CONCAT_WS(',',
        IF(email_is_valid, NULL, 'INVALID_EMAIL'),
        IF(birth_raw = '', 'MISSING_BIRTH_DATE', NULL),
        IF(birth_raw <> '' AND NOT birth_is_plausible, 'IMPLAUSIBLE_BIRTH_DATE', NULL),
        IF(city IS NULL, 'MISSING_CITY', NULL)
    ), '')
FROM deduplicated
WHERE version_rank = 1;
