---
description: Get independent second opinions from several OpenRouter models, then synthesize them yourself
argument-hint: [-m "model-a,model-b"] [-p cheap|balanced|quality|diverse] [-t N] [--run] <question>
allowed-tools: Bash(./scripts/or-panel.py:*), Read, WebSearch, WebFetch, Grep, Glob
---

Ask a panel of OpenRouter models the user's question, then **you** do the
analysis and write the final answer. You are the orchestrator and the analyst —
OpenRouter is billed only for the panel's raw opinions.

Request: **$ARGUMENTS**

## Forward the user's flags verbatim

The request above may contain script flags mixed in with the question. Split it:
anything matching a flag from the options list below is a flag, the rest is the
question. Pass the flags through to `./scripts/or-panel.py` exactly as typed and
never silently substitute your own — if the user named models with `-m`, those
are the models, even if you would have picked differently.

Two things to check before running, since both cost the user something:

- **Unknown model IDs.** The script prices them pessimistically and still sends
  them, so a typo costs a perspective at request time rather than failing fast.
  Validate first and ask about anything that doesn't resolve:
  `jq -e --arg m "<id>" '[.data[]|select(.id==$m)]|length>0' ~/.cache/openrouter-models.json`
- **Panel makeup.** If every model the user named comes from one lab, say so
  once — same-lineage models agree by construction, which wastes the run. Make
  the point, then do what they asked.

## Cost discipline — follow this exactly

This spends the user's OpenRouter credits, and they have run out before.

1. **Always estimate first.** Run without `--run`:

   ```
   ./scripts/or-panel.py [options] "<question>"
   ```

   Free endpoints only. Prints the panel, the balance, and a worst-case ceiling.

2. **Show the user** the ceiling, typical, and remaining balance. Ask whether to
   proceed. Stop there.

3. **Only on a yes** (or if their message already said `--run`), re-run the same
   command with `--run`.

If the ceiling looks high against the balance, propose `--preset cheap` or a
smaller `-t` before proposing `--run`.

## Gather the evidence yourself first

Your WebSearch, WebFetch, Read and Grep are free on the user's Claude
subscription. The panel models' web search is not. So before running the panel
on any question that needs current facts or repo context:

1. Research it yourself — search, fetch, read the relevant files.
2. Write the findings to a scratch file.
3. Pass it with `-f <file>` so every model reasons over the *same* evidence.

This is cheaper than `--online` and makes the disagreement meaningful: when the
models see identical facts, a split is a genuine difference in judgment rather
than a difference in what they happened to retrieve.

Use `--online` only when the user explicitly wants each model doing its own
independent retrieval, and mention the ~$0.007/model surcharge.

## Writing the synthesis

After a real run, read `.panel/<timestamp>.md` and write the analysis the
OpenRouter analyst would otherwise have produced — but better, because you have
the repo and the conversation in context. Structure it as:

- **Answer** — your own conclusion, informed by the panel. You are not a
  neutral summarizer; commit to a position.
- **Where they agreed** — brief. Consensus is the least informative part.
- **Where they split** — the valuable part. Name which model took which side and
  say which argument is actually stronger, with your reasoning.
- **Unique points** — anything only one model raised that survives scrutiny.
- **Blind spots** — what none of them addressed but should have.

Flag any model whose answer was marked `**truncated**` (hit the token limit), and
any that failed — their absence skews the consensus. Report the actual cost the
script printed. Don't paste the raw panel file back at the user.

## Options worth knowing

- `-p cheap|balanced|quality|diverse` — default `balanced`
- `-m "model-a,model-b"` — custom panel, 1-8 OpenRouter model IDs
- `-t N` — max tokens per answer (default 4000; biggest cost lever)
- `-s TEXT` — system prompt for every model, e.g. to force a stance or format
- `-f FILE` — context file (see above)
- `--max-spend USD` — hard guard, default 1.00

Run `./scripts/or-panel.py --help` for the full list.
