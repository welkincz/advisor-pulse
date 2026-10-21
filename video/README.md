# Weekly recap video

A 23-second video of the week, rendered with [Remotion](https://www.remotion.dev) from the
same published export the site reads. The Overview shows it as "The week in 20 seconds".

```
export (web/public/data) --pulse recap--> recap.json --remotion--> recap.mp4 + poster.jpg (web/public/recap)
```

- `src/pulse/export/recap.py` picks the numbers: four national measures, regions against
  their usual week, the biggest regional anomalies and one run summary. Its headline is the
  Overview's sentence, ported, so the two never disagree.
- `src/Recap.tsx` is six scenes. Counts settle with `spring()`, anomaly rings draw on with a
  dash offset as on the site's charts, and every scene fades in and out.
- `src/theme.ts` copies the site's light tokens; `tests/export/test_recap.py` fails if they drift.

```bash
pnpm -C video install
make video WEEK=2026-W42   # needs web/public/data (make run, or a fetched export)
pnpm -C video studio       # preview on the fixture week
```

The weekly workflow renders the latest week before the site build. The step is allowed to
fail: the site then ships without the section. Remotion is free for individuals; see its
licence before using this in a company of more than three people.
