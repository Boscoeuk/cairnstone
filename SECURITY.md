# Security Policy

## Supported versions

| version | supported |
|---|---|
| 0.1.x | yes |

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Email the maintainer privately and we will respond within 7 days:

- GitHub: use [Private vulnerability reporting](https://github.com/Boscoeuk/cairn/security/advisories/new) on this repository.

Include: a description of the issue, steps to reproduce or a proof of concept, affected
versions/commits, and your assessment of impact. If you can, include a suggested fix.

## What to expect

1. Acknowledgement within 7 days.
2. A private assessment of severity and a fix timeline.
3. A fix and, where appropriate, a coordinated disclosure note in `CHANGELOG.md`.
   We credit reporters by name unless you ask to stay anonymous.

## Scope notes

Cairn is a **local-first** tool: model inference and data stay on the local network by
design. Reports that a cloud endpoint is reachable would be a design violation, not a
vulnerability — but if you find a code path that *does* call a cloud service, that is
in scope and we want to know.
