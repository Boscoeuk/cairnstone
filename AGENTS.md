# AGENTS.md — worker contract

You are a worker agent driven by a coding agent. the maintainer is the project manager and the only Hermes agent
involved. Read this file and the brief you were given before writing code.

## Rules

1. **Local only.** Model endpoints are `glm-5.3-flash` and `local-judge` (see `the local endpoint configuration`).
   Embeddings are `http://127.0.0.1:1234/v1`. Never call a cloud API.
2. **Work only inside `~/cairn`.** Do not touch other directories.
3. **Run what you write.** Before reporting, execute the code and paste the real command and its
   real output. Never describe what the code would do.
4. **No fabrication.** If a dataset field is missing, say so. Do not invent sample data.
5. **Small, reviewable diffs.** One concern per change. Keep functions short.
6. **Tests.** New behaviour gets a test. Run `pytest -q` and report the result.
7. **Cite evidence in your final message**: files changed, commands run, output observed,
   and anything you could not verify.
8. **Stop and report** rather than guessing when a dependency is missing or an endpoint is down.

## Reporting format

```
DONE: <one line>
FILES: <paths>
RAN: <exact commands>
OUTPUT: <key lines of real output>
UNVERIFIED: <anything not proven>
```

If you cannot finish: `BLOCKED: <reason> — <what you need>`.
