-- Current client dimension (PLAN.md §6.8). Tenure and age use one as-of date for
-- the whole dimension: `client_as_of_date` when passed, otherwise the latest client
-- update in the warehouse (America/Toronto). Neither uses the wall clock.
with client as (
    select * from {{ ref('stg_client') }}
),

{% if var('client_as_of_date', none) is not none %}
as_of as (
    select cast('{{ var("client_as_of_date") }}' as date) as as_of_date
),
{% else %}
as_of as (
    select max({{ toronto_date('last_updated_ts') }}) as as_of_date
    from client
),
{% endif %}

banded as (
    select
        client.*,
        as_of.as_of_date,
        -- Completed years, anniversary method. date_diff('year') counts calendar years only.
        date_diff('year', client.client_since_date, as_of.as_of_date)
            - case
                when month(as_of.as_of_date) < month(client.client_since_date)
                    or (
                        month(as_of.as_of_date) = month(client.client_since_date)
                        and day(as_of.as_of_date) < day(client.client_since_date)
                    )
                then 1
                else 0
            end as tenure_years,
        -- No full date of birth on the source (PLAN.md §6.2), so age is the year gap.
        year(as_of.as_of_date) - client.birth_year as age_years
    from client
    cross join as_of
)

select
    md5(client_id) as client_sk,
    client_id,
    segment_code,
    case
        when tenure_years < 1 then '<1'
        when tenure_years < 3 then '1-2'
        when tenure_years < 5 then '3-4'
        when tenure_years < 10 then '5-9'
        else '10+'
    end as tenure_band,
    case
        when age_years < 25 then '<25'
        when age_years < 35 then '25-34'
        when age_years < 45 then '35-44'
        when age_years < 55 then '45-54'
        when age_years < 65 then '55-64'
        else '65+'
    end as age_band,
    fsa_code,
    province_code,
    postal_valid_flag,
    primary_advisor_id,
    primary_branch_id,
    status_code = 'A' as is_active,
    client_since_date as client_since
from banded
