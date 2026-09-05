# Security Policy

PHNTM is a security tool. We take vulnerabilities in our own code as seriously
as the ones it helps you find.

## Reporting

- **Do NOT open a public issue** for security problems.
- Report privately via GitHub's Security Advisories:
  https://github.com/merouanebenboucherit-cmd/phntm/security/advisories/new
- Or email the maintainers directly (address listed in your profile).

Please include: affected version, a repro (as minimal as possible), and impact.
Maintainers typically triage within 7 days.

## Scope

- The `phntm` CLI and its engine (`phntm/engine/*`)
- Catalog data integrity (bad URLs, checksum bypass, malicious components)
- Anything that would make a *built stick* unsafe when booted on a target machine

## Out of scope

- Vulnerabilities in third-party ISOs/components the catalog points at
  (report those upstream)
- Physical attacks requiring local access to the machine running PHNTM

## Our promise

- No telemetry, no phone-home, no network access unless you run an update command.
- Every downloaded component should be pinned by `sha256` + `release`; if you find
  a path where a build proceeds without verification, that's a bug — report it.