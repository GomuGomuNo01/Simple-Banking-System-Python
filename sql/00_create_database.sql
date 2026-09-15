-- =====================================================================
-- 00. Database creation
-- Run manually in PyCharm (Database tool window) or through the pipeline:
--   python -m sbs_bank.pipeline all
-- utf8mb4 stores every character (accents, emojis); the _0900_ai_ci
-- collation compares text without case or accent sensitivity.
-- =====================================================================

DROP DATABASE IF EXISTS sbs_bank;
CREATE DATABASE sbs_bank CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE sbs_bank;
