{#- Postal codes (PLAN.md §6.6, DQ011): drop spaces and hyphens, upper-case, re-space as
    `A1A 1A1`, then check patterns.POSTAL_CODE. Anything that still fails is null. -#}

{% macro normalized_postal(raw) -%}
    nullif(
        regexp_extract(
            regexp_replace(regexp_replace(upper(trim({{ raw }})), '[ -]', '', 'g'), '^(.{3})', '\1 '),
            '^[ABCEGHJ-NPRSTVXY][0-9][ABCEGHJ-NPRSTV-Z] [0-9][ABCEGHJ-NPRSTV-Z][0-9]$'
        ),
        ''
    )
{%- endmacro %}

{#- FSA of a raw postal code, or 'UNK' when it does not normalize. -#}
{% macro fsa_code(raw) -%}
    coalesce(substr({{ normalized_postal(raw) }}, 1, 3), 'UNK')
{%- endmacro %}
