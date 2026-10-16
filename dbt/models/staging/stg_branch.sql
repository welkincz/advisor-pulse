-- One row per branch_id, the latest LAST_UPD_TS, plus district and region codes from
-- reference/org.yaml (PLAN.md §6.6). The seed export is a later issue, so the hierarchy
-- is inlined here. A missing district fails the not_null tests on the joined columns.
with renamed as (
    select
        "BRNCH_ID" as branch_id,
        nullif(trim("BRNCH_NM"), '') as branch_name,
        nullif(upper(trim("DIST_CD")), '') as district_code,
        nullif(upper(trim("FSA_CD")), '') as fsa_code,
        cast("OPEN_DT" as date) as open_date,
        cast("CLOSE_DT" as date) as close_date,
        cast("LAST_UPD_TS" as timestamp with time zone) as last_updated_ts,
        "_batch_id",
        "_loaded_at" as _loaded_at,
        "_source_row" as _source_row
    from {{ source('raw', 'teradata__brnch') }}
),

deduped as (
    select *
    from renamed
    where branch_id is not null
    qualify row_number() over (
        partition by branch_id
        order by last_updated_ts desc, _loaded_at desc, _source_row desc
    ) = 1
),

org_district as (
    select *
    from (
        values
        ('GTA', 'GTA', 'ON', 'Ontario'),
        ('EON', 'Eastern Ontario', 'ON', 'Ontario'),
        ('SWO', 'Southwestern Ontario', 'ON', 'Ontario'),
        ('NON', 'Northern Ontario', 'ON', 'Ontario'),
        ('MTL', 'Greater Montréal', 'QC', 'Quebec'),
        ('QCE', 'Québec City & East', 'QC', 'Quebec'),
        ('WQC', 'Western Quebec', 'QC', 'Quebec'),
        ('BCL', 'BC Lower Mainland', 'WE', 'West'),
        ('BCI', 'BC Interior & North', 'WE', 'West'),
        ('ABT', 'Alberta', 'WE', 'West'),
        ('PRA', 'Prairies (SK/MB)', 'WE', 'West'),
        ('NSP', 'Nova Scotia & PEI', 'AT', 'Atlantic'),
        ('NBK', 'New Brunswick', 'AT', 'Atlantic'),
        ('NFL', 'Newfoundland & Labrador', 'AT', 'Atlantic')
    ) as district (district_code, district_name, region_code, region_name)
)

select
    deduped.branch_id,
    deduped.branch_name,
    deduped.district_code,
    org_district.district_name,
    org_district.region_code,
    org_district.region_name,
    deduped.fsa_code,
    deduped.open_date,
    deduped.close_date,
    deduped.last_updated_ts,
    deduped._batch_id
from deduped
left join org_district on org_district.district_code = deduped.district_code
