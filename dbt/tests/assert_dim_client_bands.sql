-- Tenure and age bands follow the rules in dim_client.sql, and the latest book week
-- agrees with the current dimension (same advisor, branch, and active flag).
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

expected as (
    select
        client.client_id,
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
        end as age_band
    from (
        select
            client.client_id,
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
            year(as_of.as_of_date) - client.birth_year as age_years
        from client
        cross join as_of
    ) as client
),

band_failures as (
    select
        expected.client_id,
        'band' as check_name,
        expected.tenure_band as expected_tenure_band,
        dim.tenure_band as actual_tenure_band,
        expected.age_band as expected_age_band,
        dim.age_band as actual_age_band
    from expected
    inner join {{ ref('dim_client') }} as dim on dim.client_id = expected.client_id
    where dim.tenure_band is distinct from expected.tenure_band
        or dim.age_band is distinct from expected.age_band
),

count_failures as (
    select
        cast(null as varchar) as client_id,
        'row_count' as check_name,
        cast(null as varchar) as expected_tenure_band,
        cast(null as varchar) as actual_tenure_band,
        cast(null as varchar) as expected_age_band,
        cast(null as varchar) as actual_age_band
    where (select count(*) from {{ ref('dim_client') }})
        <> (select count(*) from {{ ref('stg_client') }})
),

latest_book as (
    select *
    from {{ ref('int_client_book_weekly') }}
    where week_end = (select max(week_end) from {{ ref('int_client_book_weekly') }})
),

book_failures as (
    select
        coalesce(dim.client_id, book.client_id) as client_id,
        'latest_week' as check_name,
        dim.primary_advisor_id as expected_tenure_band,
        book.primary_advisor_id as actual_tenure_band,
        dim.primary_branch_id as expected_age_band,
        book.primary_branch_id as actual_age_band
    from {{ ref('dim_client') }} as dim
    full outer join latest_book as book on dim.client_id = book.client_id
    where dim.client_id is null
        or book.client_id is null
        or dim.primary_advisor_id is distinct from coalesce(book.primary_advisor_id, 'UNKNOWN')
        or dim.primary_branch_id is distinct from book.primary_branch_id
        or dim.is_active is distinct from book.is_active
)

select * from band_failures
union all
select * from count_failures
union all
select * from book_failures

{% if target.name == 'ci' %}
union all
-- Hand-checked against client_since and birth year at as-of 2026-10-04.
select
    examples.client_id,
    'hand_example' as check_name,
    examples.tenure_band as expected_tenure_band,
    dim.tenure_band as actual_tenure_band,
    examples.age_band as expected_age_band,
    dim.age_band as actual_age_band
from (
    select *
    from (
        values
            ('CLI-00000126', '<1', '35-44'),
            ('CLI-00000203', '<1', '25-34'),
            ('CLI-00000017', '1-2', '55-64'),
            ('CLI-00000028', '3-4', '55-64'),
            ('CLI-00000020', '5-9', '65+'),
            ('CLI-00000004', '10+', '25-34'),
            ('CLI-00000009', '10+', '<25'),
            ('CLI-00000001', '5-9', '65+')
    ) as t(client_id, tenure_band, age_band)
) as examples
left join {{ ref('dim_client') }} as dim on dim.client_id = examples.client_id
where dim.client_id is null
    or dim.tenure_band is distinct from examples.tenure_band
    or dim.age_band is distinct from examples.age_band
    or (select as_of_date from as_of) <> date '2026-10-04'
{% endif %}
