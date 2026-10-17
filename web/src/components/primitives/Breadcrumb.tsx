import { Link } from 'react-router-dom'

export interface Crumb { label: string; to?: string }

/** The drill path, National to Advisor. The last crumb is the current page and is not a link. */
export function Breadcrumb({ items }: { items: readonly Crumb[] }) {
  return <nav className="breadcrumb" aria-label="Breadcrumb">
    <ol>
      {items.map((item, index) => {
        const current = index === items.length - 1
        return <li key={`${index}-${item.label}`}>
          {current || !item.to ? <span aria-current={current ? 'page' : undefined}>{item.label}</span> : <Link to={item.to}>{item.label}</Link>}
        </li>
      })}
    </ol>
  </nav>
}
