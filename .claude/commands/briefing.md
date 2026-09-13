---
description: Research the evidence a scope round asked for and write the briefing the answer panel reasons over
argument-hint: <topic> [scope-report]
allowed-tools: Read, Write, Glob, Grep, WebSearch, WebFetch
---

Topic: **$1** · Scope report: **$2** — when empty, the newest `SCOPE-*.md` in `.panel/$1/`.

The panel has already said what it would need to know. Your job is to go and find it,
and leave behind one file the answer round reasons over:

```
.panel/$1/SCOPE-<stamp>.md  →  research  →  questions/$1/briefing.md
```

You are not summarising the scope report, you are satisfying it. A briefing that hands
the panel back its own questions is worse than no briefing, because the answer round is
told to treat it as primary evidence.

## Read the round

Take the **union** of what the panelists asked for. A point only one model raised is
exactly what a single researcher would have missed. Order the needs by how much the
answer turns on them; several panelists asking for the same thing tells you where it
belongs in that order.

Then read `questions/$1/question.md`. Whatever the owner settled there is not yours to
research — their knowledge enters through the question, and it is current.

## Do the research

The scope prompt forbids URLs, so the panel names works instead of linking them. Find
those works, read them, and cite what you actually read. A named work you cannot find or
reach goes in the briefing as exactly that — a dead lead is information.

- **Neutral.** Findings, not conclusions. No recommendation, and no framing that favours
  an answer: a briefing that argues a side anchors every panelist at once and destroys
  the independence the panel is being paid for.
- **Compressed.** Every panelist is sent the whole briefing, so its length is paid for
  once per model. Extract the passages and figures that bear on the question. Do not
  paste pages.
- **Sourced and dated.** Every finding carries where it came from, and its date wherever
  the date could matter.
- **Explicit about gaps.** What you could not settle goes in as unsettled. The answer
  role is told that a marked gap beats a confident guess; this is where that is
  collected on.

Add what is obviously missing even if nobody asked for it — local context, repository
files, anything time-sensitive that training data could not cover.

## Write `questions/$1/briefing.md`

Markdown, in this order:

1. `# Briefing — <first line of question.md>`, then one italic line naming the scope
   report it came from and today's date. That heading becomes the answer report's title.
2. One `##` section per need, in priority order. The heading names the need in plain
   words, the body is the evidence, the last line is `Source: <work, publisher, date>`.
3. `## Not settled` — one line each for what you could not answer and what would settle
   it. If everything was settled, say so under the heading rather than dropping it.
4. `---`, then the full text of `questions/$1/question.md`, verbatim.

The last part is not decoration. The briefing is passed to the panel as the entire
prompt, so the question has to be inside it — and keeping it verbatim means a briefing
that has drifted from a re-edited question is caught by diffing its tail.

If `questions/$1/briefing.md` already exists, say so and ask before overwriting. It is
tracked, and a previous round's research is easy to lose.

## Report back

Say what you settled, what you could not, and where the file is. Do not run the answer
panel — that is `questions/$1/answer.sh`, when the user is ready.
