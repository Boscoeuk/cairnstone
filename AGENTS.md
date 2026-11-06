# AGENTS.md — guidance for AI coding agents

This file is for AI coding agents working in this repository. Read it before writing code.

## Rules

1. **Local inference only.** Every model call goes to an OpenAI-compatible endpoint on the local
   network, configured by `CAIRN_BASE_URL` / `CAIRN_MODEL` (see README). Embeddings come from a
   local endpoint too. Never call a cloud API.
2. **Work only inside this repository.** Do not touch files outside it.
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
