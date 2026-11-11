-- MetricFlow's daily time spine, taken from the main project's calendar.
select date_day from {{ source('pulse_marts', 'dim_date') }}
