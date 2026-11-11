# Out of scope: Scala, Java and Go

- Status: Decided by the owner, 2026-11-11 ([decision on #326](https://github.com/welkincz/advisor-pulse/issues/326#issuecomment-6804404039))
- Issue: #326 (gap found by #299)

## Decision

Advisor Pulse stays a Python and SQL batch with a TypeScript site. It will not add a Scala,
Java or Go component. The reviewer map keeps this competency graded **missing**.

## Why

- **One language per layer is the design.** Contracts, generator, loaders, runner and
  narrative are Python; models are dbt SQL; the site is TypeScript. Contracts generate the
  schemas, dbt sources and TypeScript types from one place
  ([README](../../README.md#L28)). A service in another language would need its own types,
  build and CI just to show the language.
- **No part of the weekly batch needs it.** A weekly run is a single-machine batch measured
  in minutes ([baseline](../baseline.md)); there is no low-latency service or JVM engine to
  write.
- **Honesty.** A component added only to show a language would read as systems experience
  it is not.

## If it is revisited

The honest route is a separate, self-contained lab with its own build, tests and a measured
run, kept out of the weekly pipeline. Nothing here claims Scala, Java or Go experience.
