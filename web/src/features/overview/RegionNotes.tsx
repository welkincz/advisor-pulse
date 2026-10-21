import { Link } from 'react-router-dom'
import { useNarrative } from '../../data'
import { REGION_ORDER } from '../../data/regions'

function Note({ week, id, href }: { week: string; id: string; href: string }) {
  const narrative = useNarrative(week, id)
  if (narrative.status !== 'ready') return null
  const { headline, bullets, fallback } = narrative.data
  return <li className="note">
    <p className="note-headline">{headline}</p>
    {bullets[0] && <p className="note-detail">{bullets[0].text}</p>}
    <p className="note-meta">{fallback ? 'Template summary' : 'Written by Claude from the week’s figures, then checked against them'}. <Link to={href}>Read the full note</Link></p>
  </li>
}

/** The regional narratives for the week, when the run published them; nothing otherwise. */
export function RegionNotes({ week, hrefFor }: { week: string; hrefFor: (id: string) => string }) {
  return <ul className="notes">
    {REGION_ORDER.map((id) => <Note key={`${week}-${id}`} week={week} id={id} href={hrefFor(id)} />)}
  </ul>
}
