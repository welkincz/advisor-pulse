/* =====================================================================
   BRANCH WEEKLY CONTACT REPORT  --  "legacy" job (SYNTHETIC EXERCISE)
   ---------------------------------------------------------------------
   Written on purpose in an old procedural style for the #324 lab: one
   monolithic script, temp tables step by step, nested and correlated
   subqueries, a hard-coded calendar. It is NOT real SAS and was never a
   production job. It reads the landed raw tables of the fixture
   warehouse (after ingest quarantine) and nothing from dbt.

   Known quirks, kept on purpose (see ../mapping.toml):
     Q1  BRNCH_CD is the bare 4-digit code ('0101'), no 'BR-' prefix.
     Q2  AVG_MTG_MIN is rounded half-up to 1 decimal place.
     Q3  AVG_MTG_MIN is 0 (not missing) when no meeting was held.
   ===================================================================== */

/* STEP 01  hard-coded reporting calendar (Mon-Sun, America/Toronto).
            Maintained by hand: add next quarter's weeks before it starts. */
CREATE OR REPLACE TEMP TABLE T01_CAL AS
SELECT * FROM (VALUES
    ('2026-W37', DATE '2026-09-07', DATE '2026-09-13'),
    ('2026-W38', DATE '2026-09-14', DATE '2026-09-20'),
    ('2026-W39', DATE '2026-09-21', DATE '2026-09-27'),
    ('2026-W40', DATE '2026-09-28', DATE '2026-10-04')
) AS C (RPT_WK_ID, WK_START_DT, WK_END_DT);

/* STEP 02  latest version of each activity: max UPDATED_TS, then max
            _EXTRACTED_AT, via nested subqueries; DISTINCT drops exact dups. */
CREATE OR REPLACE TEMP TABLE T02_ACT AS
SELECT DISTINCT
    A.ACTIVITY_ID, A.ADVISOR_ID, A.CLIENT_ID, A.BRANCH_ID,
    UPPER(TRIM(A.ACTIVITY_TYPE)) AS ACT_TYP,
    UPPER(TRIM(A.STATUS)) AS ACT_STAT,
    A.DURATION_MIN,
    CAST(TIMEZONE('America/Toronto', A.ACTIVITY_TS) AS DATE) AS ACT_DT
FROM wh.raw.snowflake__activity A
WHERE A.ACTIVITY_ID IS NOT NULL
  AND A.UPDATED_TS = (SELECT MAX(B.UPDATED_TS) FROM wh.raw.snowflake__activity B
                      WHERE B.ACTIVITY_ID = A.ACTIVITY_ID)
  AND A._EXTRACTED_AT = (SELECT MAX(C._EXTRACTED_AT) FROM wh.raw.snowflake__activity C
                         WHERE C.ACTIVITY_ID = A.ACTIVITY_ID
                           AND C.UPDATED_TS = A.UPDATED_TS);

/* STEP 03  completed activity inside the calendar only. */
CREATE OR REPLACE TEMP TABLE T03_DONE AS
SELECT T.*, K.RPT_WK_ID
FROM T02_ACT T, T01_CAL K
WHERE T.ACT_STAT = 'COMPLETED'
  AND T.ACT_TYP IN ('CALL_OUT', 'CALL_IN', 'APPOINTMENT', 'REVIEW')
  AND T.ACT_DT BETWEEN K.WK_START_DT AND K.WK_END_DT;

/* STEP 04  branch on the activity date: the latest assignment event on or
            before it (same-day ties: highest ASGN_ID). A TERM event, or no
            event at all, falls back to the branch the row was logged at. */
CREATE OR REPLACE TEMP TABLE T04_BR AS
SELECT D.*,
    COALESCE((
        SELECT CASE WHEN G.RSN_CD = 'TERM' THEN NULL ELSE G.BRNCH_ID END
        FROM wh.raw.teradata__advsr_asgn G
        WHERE G.ADVSR_ID = D.ADVISOR_ID
          AND G.ASGN_ID = (
              SELECT MAX(H.ASGN_ID) FROM wh.raw.teradata__advsr_asgn H
              WHERE H.ADVSR_ID = D.ADVISOR_ID
                AND H.EFF_DT = (SELECT MAX(I.EFF_DT) FROM wh.raw.teradata__advsr_asgn I
                                WHERE I.ADVSR_ID = D.ADVISOR_ID AND I.EFF_DT <= D.ACT_DT))
    ), D.BRANCH_ID) AS CR_BRNCH_ID
FROM T03_DONE D;

/* STEP 05  summarise by branch and week. */
CREATE OR REPLACE TEMP TABLE T05_SUM AS
SELECT
    RPT_WK_ID,
    CR_BRNCH_ID,
    COUNT(*) AS ACT_CNT,
    SUM(CASE WHEN ACT_TYP = 'CALL_OUT' THEN 1 ELSE 0 END) AS CALL_OUT_CNT,
    SUM(CASE WHEN ACT_TYP = 'CALL_IN' THEN 1 ELSE 0 END) AS CALL_IN_CNT,
    COUNT(DISTINCT CLIENT_ID) AS UNIQ_CLNT_CNT,
    SUM(CASE WHEN ACT_TYP IN ('APPOINTMENT', 'REVIEW') THEN DURATION_MIN END) AS MTG_MIN,
    SUM(CASE WHEN ACT_TYP IN ('APPOINTMENT', 'REVIEW') THEN 1 ELSE 0 END) AS MTG_CNT
FROM T04_BR
GROUP BY RPT_WK_ID, CR_BRNCH_ID;

/* STEP 06  final report layout (Q1, Q2, Q3 above). */
CREATE OR REPLACE TEMP TABLE BRANCH_CONTACT_RPT AS
SELECT
    RPT_WK_ID,
    SUBSTR(CR_BRNCH_ID, 4) AS BRNCH_CD,
    ACT_CNT,
    CALL_OUT_CNT,
    CALL_IN_CNT,
    UNIQ_CLNT_CNT,
    CASE WHEN MTG_CNT = 0 THEN 0
         ELSE FLOOR(MTG_MIN * 10.0 / MTG_CNT + 0.5) / 10.0 END AS AVG_MTG_MIN
FROM T05_SUM
ORDER BY RPT_WK_ID, BRNCH_CD;
