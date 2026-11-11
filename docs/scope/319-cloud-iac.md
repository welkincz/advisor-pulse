# Out of scope: AWS, Azure, GCP and infrastructure as code

- Status: Decided by the owner, 2026-11-11
- Issue: #319 (gap found by #299)

## Decision

Advisor Pulse will not add AWS, Azure or GCP services, or Terraform, CloudFormation or a
similar IaC tool. The reviewer map keeps this competency graded **weak**.

## Why

- **It needs paid cloud accounts.** A real demonstration means an account, billing, IAM
  roles and resources that stay up. This is a public portfolio project with no cloud budget,
  and a free-tier sketch would show the syntax, not the operations.
- **It does not serve the report.** The weekly batch runs on GitHub Actions, keeps state in
  Cloudflare R2 and deploys a static site to Cloudflare Pages. Moving those to another cloud,
  or wrapping them in IaC, would add moving parts without changing a single number.
- **Honesty.** A `main.tf` that was never applied would read as experience it is not.

## What the project does show

- Object storage as the state store between runs, with a conditional-write lock:
  [`src/pulse/state/sync.py`](../../src/pulse/state/sync.py),
  [`src/pulse/state/lock.py`](../../src/pulse/state/lock.py).
- A scheduled workflow that restores state, runs the week, deploys and persists:
  [`.github/workflows/weekly.yml`](../../.github/workflows/weekly.yml).
- Secrets from environment variables only, skipped cleanly when absent.

## If it is revisited

The honest route is a separate, self-contained lab with its own account, a plan that is
applied and destroyed, and a measured run, kept out of the weekly pipeline. Nothing in this
repository claims cloud-platform operations, employer-scale infrastructure or regulated
deployment.
