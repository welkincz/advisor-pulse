-- Client × ISO week book (PLAN.md §6.7 and §7). One row per client who already
-- existed at week end, with the portfolio, home branch and FSA on the client version in
-- force at Sunday 23:59 America/Toronto, and an active flag. The book owner is the
-- portfolio's holder on the week-end date; a null PRTF_ID (rows from before portfolios)
-- or one the master lacks (DQ014) falls back to PRIM_ADVSR_ID until #226 drops it. Coverage's
-- denominator is the active subset (`is_active`). Versions come from every loaded CLNT
-- row: staging keeps only the latest, which would hide a mid-period reassignment or move.
with renamed as (
    select
        "CLNT_ID" as client_id,
        cast("CLNT_SINCE_DT" as date) as client_since_date,
        nullif(trim("PRIM_ADVSR_ID"), '') as primary_advisor_id,
        nullif(trim("PRIM_BRNCH_ID"), '') as primary_branch_id,
        nullif(trim("PRTF_ID"), '') as portfolio_id,
        {{ fsa_code('"PSTL_CD"') }} as fsa_code,
        nullif(upper(trim("STAT_CD")), '') as status_code,
        cast("LAST_UPD_TS" as timestamp with time zone) as last_updated_ts,
        "_loaded_at" as _loaded_at,
        "_source_file" as _source_file,
        "_source_row" as _source_row
    from {{ source('raw', 'teradata__clnt') }}
),

-- One row per client per update. A later load of the same timestamp wins.
versions as (
    select *
    from renamed
    where client_id is not null and last_updated_ts is not null
    qualify row_number() over (
        partition by client_id, last_updated_ts
        order by _loaded_at desc, _source_file desc, _source_row desc
    ) = 1
),

-- A version applies from its LAST_UPD_TS until the next update. The snapshot's
-- timestamp is when that state was last touched, so earlier weeks are not invented.
ranged as (
    select
        client_id,
        client_since_date,
        primary_advisor_id,
        primary_branch_id,
        portfolio_id,
        fsa_code,
        status_code,
        last_updated_ts as valid_from,
        coalesce(
            lead(last_updated_ts) over (
                partition by client_id
                order by last_updated_ts
            ),
            cast('9999-12-31' as timestamp with time zone)
        ) as valid_to
    from versions
),

weeks as (
    select
        iso_week_id,
        min(week_start) as week_start,
        max(week_end) as week_end,
        timezone(
            'America/Toronto',
            cast(max(week_end) as timestamp) + interval 23 hour + interval 59 minute
        ) as as_of_ts
    from {{ ref('dim_date') }}
    group by iso_week_id
),

observed as (
    select
        min({{ toronto_date('valid_from') }}) as first_update,
        max({{ toronto_date('valid_from') }}) as last_update
    from ranged
)

select
    ranged.client_id,
    weeks.iso_week_id,
    weeks.week_end,
    coalesce(holder.advisor_id, ranged.primary_advisor_id) as primary_advisor_id,
    ranged.primary_branch_id,
    ranged.portfolio_id,
    holder.transit_branch_id,
    ranged.portfolio_id is not null and holder.portfolio_id is null as is_unknown_portfolio,
    ranged.fsa_code,
    ranged.status_code = 'A' as is_active
from weeks
inner join observed
    on weeks.week_end >= observed.first_update
    and weeks.week_start <= observed.last_update
inner join ranged
    on weeks.as_of_ts >= ranged.valid_from
    and weeks.as_of_ts < ranged.valid_to
    and ranged.client_since_date <= weeks.week_end
left join {{ ref('int_portfolio_history') }} as holder
    on holder.portfolio_id = ranged.portfolio_id
    and weeks.week_end >= holder.valid_from
    and weeks.week_end < holder.valid_to
