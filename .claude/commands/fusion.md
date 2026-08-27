---
description: Multi-model deliberation on a question via OpenRouter's fusion server tool
argument-hint: [--preset cheap|balanced|quality] [--run] <question>
allowed-tools: Bash(./scripts/or-fusion.sh:*), Read
---

Run a fusion query for the user: a panel of models answers independently, an
analyst compares them, and an outer model writes the final answer.

Request: **$ARGUMENTS**

## Cost discipline — follow this exactly

This command spends the user's OpenRouter credits. They have run out before, so
never call the API without an explicit go-ahead.

1. **Always estimate first.** Run the script without `--run`:

   ```
   ./scripts/or-fusion.sh [options] "<question>"
   ```

   This hits only free endpoints and prints the panel, the balance, and a
   worst-case cost ceiling.

2. **Show the user the estimate** — ceiling, typical, and remaining balance —
   and ask whether to proceed. Stop there.

3. **Only if the user says yes** (or their original message already contained
   `--run`), re-run the identical command with `--run` appended.

If the ceiling looks high relative to the balance, suggest `--preset cheap`, a
smaller `-t/--max-tokens`, or a shorter panel via `-m` before proposing `--run`.

## After a real run

The script writes `.fusion/<timestamp>.md` and `.json`. Read the `.md` and give
the user a short summary: the answer, then where the panel actually disagreed
and any blind spots — that disagreement is the part they can't get from a single
model, so lead with it rather than restating the consensus. Mention the actual
cost the script reported. Don't paste the whole file back.

## Options worth knowing

- `-p cheap|balanced|quality` — default `balanced`
- `-m "model-a,model-b"` — custom panel, 1-8 OpenRouter model IDs
- `-a MODEL` / `--outer MODEL` — analyst and final-answer models
- `-t N` — max tokens per inner call (default 6000; the biggest cost lever)
- `-c N` — web_search/web_fetch steps per model (default 3)
- `-f FILE` — prepend a file as context, e.g. notes to critique
- `--max-spend USD` — hard ceiling guard (default 1.50)

Run `./scripts/or-fusion.sh --help` if you need the full list.
