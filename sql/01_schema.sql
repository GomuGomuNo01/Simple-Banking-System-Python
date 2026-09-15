-- =====================================================================
-- 01. Schema: staging, operational tables and reference data
--
-- Layers
--   stg_*       raw data copied as-is from source files (all text columns)
--   operational tables written by the banking application
--   ref_*       reference data
--
-- Integrity is enforced by the database itself (keys, CHECK constraints)
-- so that no loading script or application bug can store an impossible
-- state such as a negative balance or a failed operation without reason.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Staging: CRM customer export, loaded without any transformation
-- ---------------------------------------------------------------------
CREATE TABLE stg_customers_raw (
    crm_customer_id VARCHAR(50),
    first_name      VARCHAR(100),
    last_name       VARCHAR(100),
    email           VARCHAR(255),
    birth_date      VARCHAR(50),
    city            VARCHAR(100),
    signup_channel  VARCHAR(50),
    updated_at      VARCHAR(50),
    loaded_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------
-- Reference data
-- ---------------------------------------------------------------------
CREATE TABLE ref_merchant_categories (
    category_code VARCHAR(30)  NOT NULL PRIMARY KEY,
    label_fr      VARCHAR(60)  NOT NULL,
    is_essential  BOOLEAN      NOT NULL
);

INSERT INTO ref_merchant_categories (category_code, label_fr, is_essential) VALUES
    ('GROCERIES',       'Alimentation',          TRUE),
    ('RESTAURANTS',     'Restaurants et cafés',  FALSE),
    ('TRANSPORT',       'Transport',             TRUE),
    ('ONLINE_SHOPPING', 'Achats en ligne',       FALSE),
    ('UTILITIES',       'Énergie et télécom',    TRUE),
    ('LEISURE',         'Loisirs',               FALSE),
    ('HEALTH',          'Santé',                 TRUE),
    ('TRAVEL',          'Voyages',               FALSE),
    ('OTHER',           'Autres',                FALSE);

-- Analysis parameters: results are computed "as of" period_end, so new
-- operations made later with the application do not change the study.
CREATE TABLE ref_analysis_period (
    period_id     TINYINT  NOT NULL PRIMARY KEY,
    period_start  DATETIME NOT NULL,
    period_end    DATETIME NOT NULL,
    dormancy_days SMALLINT NOT NULL COMMENT 'Days without activity after which an account is dormant',
    CONSTRAINT chk_period_single_row CHECK (period_id = 1)
);

INSERT INTO ref_analysis_period VALUES (1, '2025-01-01 00:00:00', '2026-06-30 23:59:59', 90);

-- ---------------------------------------------------------------------
-- Customers (cleaned from staging by 02_clean_customers.sql)
-- ---------------------------------------------------------------------
CREATE TABLE customers (
    customer_id     INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    first_name      VARCHAR(100) NOT NULL,
    last_name       VARCHAR(100) NOT NULL,
    email           VARCHAR(255) NULL,
    birth_date      DATE         NULL,
    city            VARCHAR(100) NULL,
    signup_channel  ENUM('MOBILE', 'WEB', 'PARTNER') NOT NULL,
    crm_updated_at  DATETIME     NOT NULL,
    dq_flags        VARCHAR(255) NULL COMMENT 'Data quality issues detected during cleaning',
    UNIQUE KEY uq_customers_email (email)
);

-- ---------------------------------------------------------------------
-- Accounts: one payment card per account (table "card" of the original brief)
-- ---------------------------------------------------------------------
CREATE TABLE accounts (
    account_id   INT UNSIGNED  NOT NULL AUTO_INCREMENT PRIMARY KEY,
    customer_id  INT UNSIGNED  NOT NULL,
    card_number  CHAR(16)      NOT NULL,
    pin_hash     VARCHAR(128)  NOT NULL,
    balance      DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    status       ENUM('ACTIVE', 'CLOSED') NOT NULL DEFAULT 'ACTIVE',
    opened_at    DATETIME      NOT NULL,
    closed_at    DATETIME      NULL,
    UNIQUE KEY uq_accounts_card_number (card_number),
    KEY idx_accounts_customer (customer_id),
    CONSTRAINT fk_accounts_customer FOREIGN KEY (customer_id) REFERENCES customers (customer_id),
    CONSTRAINT chk_accounts_balance_positive CHECK (balance >= 0),
    CONSTRAINT chk_accounts_card_format CHECK (card_number REGEXP '^400000[0-9]{10}$'),
    CONSTRAINT chk_accounts_closing CHECK ((status = 'CLOSED') = (closed_at IS NOT NULL))
);

-- ---------------------------------------------------------------------
-- Operation log: every attempt, successful or not (audit trail)
-- ---------------------------------------------------------------------
CREATE TABLE operation_log (
    operation_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    account_id       INT UNSIGNED    NULL COMMENT 'NULL when the card typed at login is unknown',
    event_type       ENUM('CREATE_ACCOUNT', 'LOGIN', 'BALANCE_INQUIRY', 'DEPOSIT', 'WITHDRAWAL',
                          'TRANSFER', 'CARD_PAYMENT', 'CLOSE_ACCOUNT') NOT NULL,
    status           ENUM('SUCCESS', 'FAILED') NOT NULL,
    failure_reason   ENUM('WRONG_PIN', 'UNKNOWN_CARD', 'INVALID_CARD_NUMBER', 'SAME_ACCOUNT',
                          'ACCOUNT_CLOSED', 'INVALID_AMOUNT', 'INSUFFICIENT_FUNDS') NULL,
    channel          ENUM('APP', 'CARD_NETWORK', 'SEPA') NOT NULL,
    amount_requested DECIMAL(12,2)   NULL,
    created_at       DATETIME        NOT NULL,
    KEY idx_oplog_account_date (account_id, created_at),
    KEY idx_oplog_type_status_date (event_type, status, created_at),
    CONSTRAINT fk_oplog_account FOREIGN KEY (account_id) REFERENCES accounts (account_id),
    CONSTRAINT chk_oplog_failure_reason CHECK ((status = 'FAILED') = (failure_reason IS NOT NULL))
);

-- ---------------------------------------------------------------------
-- Transactions: money movements, one per successful monetary operation
-- ---------------------------------------------------------------------
CREATE TABLE transactions (
    transaction_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    operation_id      BIGINT UNSIGNED NOT NULL,
    txn_type          ENUM('DEPOSIT', 'WITHDRAWAL', 'TRANSFER', 'CARD_PAYMENT') NOT NULL,
    from_account_id   INT UNSIGNED    NULL,
    to_account_id     INT UNSIGNED    NULL,
    amount            DECIMAL(12,2)   NOT NULL,
    merchant_category VARCHAR(30)     NULL,
    created_at        DATETIME        NOT NULL,
    UNIQUE KEY uq_transactions_operation (operation_id),
    KEY idx_txn_from_date (from_account_id, created_at),
    KEY idx_txn_to_date (to_account_id, created_at),
    KEY idx_txn_type_date (txn_type, created_at),
    CONSTRAINT fk_txn_operation FOREIGN KEY (operation_id) REFERENCES operation_log (operation_id),
    CONSTRAINT fk_txn_from_account FOREIGN KEY (from_account_id) REFERENCES accounts (account_id),
    CONSTRAINT fk_txn_to_account FOREIGN KEY (to_account_id) REFERENCES accounts (account_id),
    CONSTRAINT fk_txn_category FOREIGN KEY (merchant_category) REFERENCES ref_merchant_categories (category_code),
    CONSTRAINT chk_txn_amount_positive CHECK (amount > 0),
    CONSTRAINT chk_txn_direction CHECK (
        (txn_type = 'DEPOSIT' AND from_account_id IS NULL AND to_account_id IS NOT NULL)
        OR (txn_type IN ('WITHDRAWAL', 'CARD_PAYMENT') AND from_account_id IS NOT NULL AND to_account_id IS NULL)
        OR (txn_type = 'TRANSFER' AND from_account_id IS NOT NULL AND to_account_id IS NOT NULL
            AND from_account_id <> to_account_id)
    ),
    CONSTRAINT chk_txn_category CHECK ((txn_type = 'CARD_PAYMENT') = (merchant_category IS NOT NULL))
);
