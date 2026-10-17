-- Data-quality rule × ISO week (PLAN.md §6.8, §8), exported as dq_weekly.parquet. Ingest
-- and staging rules count rows in that week's batch; DQ011 counts the active client book
-- at week end, since a bad postal code matters for as long as the client is in the book.
with batches as (
    select * from {{ ref('int_ingest_weekly') }}
),

rules (rule_id, rule_name, action) as (
    values
        ('DQ001', 'Null ACTIVITY_ID', 'QUARANTINE'),
        ('DQ002', 'Enum not in contract', 'QUARANTINE'),
        ('DQ003', 'DURATION_MIN out of range', 'QUARANTINE'),
        ('DQ004', 'ACTIVITY_TS out of range', 'QUARANTINE'),
        ('DQ005', 'Unparseable value', 'QUARANTINE'),
        ('DQ010', 'Duplicate or re-sent row', 'DEDUPE'),
        ('DQ011', 'Invalid postal code', 'NORMALIZE'),
        ('DQ012', 'Unknown advisor_id', 'MAP_UNKNOWN')
),

book as (
    select
        iso_week_id,
        count(*) filter (where fsa_code = 'UNK') as invalid_postal,
        count(*) as active_clients
    from {{ ref('int_client_book_weekly') }}
    where is_active
    group by iso_week_id
),

counted as (
    select
        batches.iso_week_id,
        rules.rule_id,
        rules.rule_name,
        rules.action,
        case rules.rule_id
            when 'DQ001' then batches.dq001_rows
            when 'DQ002' then batches.dq002_rows
            when 'DQ003' then batches.dq003_rows
            when 'DQ004' then batches.dq004_rows
            when 'DQ005' then batches.dq005_rows
            when 'DQ010' then batches.dedupe_rows
            when 'DQ011' then coalesce(book.invalid_postal, 0)
            when 'DQ012' then batches.unknown_advisor_rows
        end as rows_affected,
        case rules.rule_id
            when 'DQ005' then batches.client_rows
            when 'DQ011' then coalesce(book.active_clients, 0)
            else batches.activity_rows
        end as rows_in_batch
    from batches
    cross join rules
    left join book using (iso_week_id)
)

select
    iso_week_id,
    rule_id,
    rule_name,
    action,
    cast(rows_affected as bigint) as rows_affected,
    cast(rows_in_batch as bigint) as rows_in_batch,
    round(rows_affected / nullif(rows_in_batch, 0), 4) as rate
from counted
