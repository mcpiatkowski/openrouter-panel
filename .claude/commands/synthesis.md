---
description: Read an answer round and write the analysis — your conclusion, where the panel split, and what the next round needs
argument-hint: <topic> [answer-report]
allowed-tools: Read, Write, Glob, Grep
---

Topic: **$1** · Answer report: **$2** — when empty, the newest `ANSWER-*.md` in `.panel/$1/`.

The panel has answered. Every panelist read the same briefing and none of them saw
another's reply, so where they diverge, the divergence is judgment — not a difference in
what each happened to find. That is what this pipeline buys, and reading it is your job:

```
.panel/$1/ANSWER-<stamp>.md  →  your analysis  →  questions/$1/synthesis.md
```

You are the analyst, not a summariser. Their answers are evidence about the question; the
synthesis is your answer to it.

## Read the round

**The answer report is the only file you open.** It holds everything this analysis needs:
the panel table, the full briefing in the `<question>` block, and every answer. The question
itself is at the end of that briefing, after the `---`. Wherever this command says *the
briefing*, it means that copy and no other.

Do not open `questions/$1/briefing.md`, and do not diff it against the report. That file is
the working copy for the *next* round and is meant to drift; the report is the record of
*this* one. A difference between them is not a finding and is not worth a line of your
output — while a panelist's citation checked against a text nobody sent it is worse than
not checking at all.

Start with the status of every panelist, from the table at the top:

- `answered` — usable.
- `truncated` — the text is real but stops mid-thought. Use it, and say it is partial.
- `no-answer` — billed in full, no text. **That model did not participate.** Never read
  its silence as agreement.
- `failed` — no opinion at all.

A three-model consensus in which one model was silent is a two-model consensus. Say so.

## Four things only this pipeline lets you check

**Did they use the briefing?** Each panelist was told to say which part it relied on.
Where one cites a section, check that the briefing says what the citation claims. A
confident citation of something the briefing does not contain is a more serious finding
than any disagreement.

**Did they respect the gaps?** The briefing's `## Not settled` is the control. A panelist
answering one of those points with confidence is filling it from its own training, which
is exactly what its role forbade. Name it, and read the rest of that answer with the same
suspicion.

**Is the agreement earned?** Panelists may agree because the briefing settled the point,
which is strong, or because they share training data, which is weak. Say which. Where you
cannot tell, write that down too.

**Where do they split?** The valuable part, and it gets the most room. Name which panelist
took which side, say which argument is stronger and why. Do not average them into a middle
position none of them held. Where a split traces back to something the briefing left
unsettled, say so — that is the next round's work.

## Write `questions/$1/synthesis.md`

Unlike the briefing, this file is for the owner and not for a panel: name the report, name
the models, quote them freely. Write in the language of the question.

Markdown, in this order:

1. `# Synteza — <the subject, as the question names it>`, or the equivalent in that
   language, then one italic line: which answer report, which panel, how many answered,
   and the date.
2. **Your conclusion**, in the first paragraph, before any discussion. You have read the
   question, the briefing and every answer, so you are better placed than any single
   panelist — and a synthesis that will not say what it thinks is worth nothing.
3. Where they agreed, briefly, each point marked earned or unearned.
4. Where they split, at length, with your verdict on each.
5. Anything one panelist raised alone that survives scrutiny.
6. Anything a panelist got wrong: a misread of the briefing, a gap filled from training, a
   claim no source supports.
7. **What the next round needs** — the concrete edits. What the owner must measure and add
   to `question.md`; what the briefing should have covered and did not. If the honest
   answer is that the panel has gone as far as the evidence allows, say that instead.

If `questions/$1/synthesis.md` already exists, say so and ask before overwriting.

## Do not research

If a claim needs checking against the world rather than against the briefing, do not go
and check it — record it under what the next round needs. New evidence enters this
pipeline through `/briefing`, once, where every panelist sees the same of it. A synthesis
that quietly adds its own facts breaks that, and it is the only thing that makes the
panel's disagreement mean anything.

## Report back

Give the conclusion and the sharpest split in the chat, plus the path to the file. If the
round was weakened — a silent panelist, a truncated answer, a briefing gap that decided
the outcome — say that first.
