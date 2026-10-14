# Advisor Pulse web scaffold

Run `make web-dev` from the repository root for the Vite route shells. During development,
`/data/*` serves matching files from `fixtures/exports/`. The weekly export pipeline will
create that directory; until then, the route shells do not show report data.

`make web-types` generates one committed TypeScript file per JSON Schema in
`contracts/schemas/`. `make web-check` checks those files for drift, runs ESLint and the
raw-colour guard, typechecks, builds, and runs Chromium smoke tests. The colour values
from charliebuild are confined to `src/theme/tokens.css`.
