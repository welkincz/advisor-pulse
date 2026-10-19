/** The weekly pipeline as an ordered flow; it wraps to a vertical list on narrow screens. */
const steps = [
  ['Seeded generator', 'Two source systems and a defect manifest'],
  ['Ingest', 'Watermarks, file manifest, quarantine'],
  ['dbt', 'Staging, intermediate, marts'],
  ['Checks', 'Freshness, volume, quarantine rate, reconciliation'],
  ['Narrative', 'Grounded, validated, cached'],
  ['Export', 'Parquet and JSON'],
  ['Static site', 'DuckDB-WASM in the browser'],
] as const

export function ArchitectureDiagram() {
  return <figure className="cs-diagram" aria-labelledby="cs-diagram-caption">
    <ol className="cs-flow">
      {steps.map(([name, detail]) => <li key={name}><strong>{name}</strong><span>{detail}</span></li>)}
    </ol>
    <ul className="cs-stores">
      <li><strong>R2 state</strong><span>Sources and warehouse persist between weekly runs</span></li>
      <li><strong>Run log</strong><span>Every stage attempt, timing and row count, published with the site</span></li>
    </ul>
    <figcaption id="cs-diagram-caption">One weekly run, from generated sources to the published report.</figcaption>
  </figure>
}
