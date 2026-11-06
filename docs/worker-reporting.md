# Worker reporting

The login shell echoes zshrc function bodies into captured stdout, so a worker's printed report
can be drowned in noise. Therefore:

- Every worker writes its report to `reports/<phase>-report.md` in the repo, in the AGENTS.md
  format, **and** prints it.
- The file is the authoritative record. The maintainer reads the file, not the captured terminal tail.
- `reports/` is committed so the evidence trail survives the session.
