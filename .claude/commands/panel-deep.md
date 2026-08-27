---
description: Three-phase research panel — the models scope the evidence, you fetch it, then they answer on a shared briefing
argument-hint: [-p preset] [-m "model-a,model-b"] [--budget USD] <research question>
allowed-tools: Bash(./scripts/or-panel.py:*), Read, Write, WebSearch, WebFetch, Grep, Glob
---

A deeper version of `/panel`. Instead of answering cold or each paying to search
separately, the panel first says what evidence it needs, **you** gather it, and
then they all answer on one shared briefing.

Question: **$ARGUMENTS**

Why this shape: prefetching evidence yourself makes disagreement interpretable
(same facts, different judgment) but propagates your search blind spots to every
model at once. Letting the panel scope the evidence first removes that single
point of failure while keeping the evidence shared. See `/panel` for the plain
single-round version — prefer it for anything that isn't genuinely a research
question.

## Phase 0 — one estimate, one approval

Run the phase-1 estimate and project phase 3, then ask **once** for the whole
flow rather than stopping at every phase:

```
./scripts/or-panel.py -t 600 [-p/-m …] "<question>"     # phase 1 ceiling
```

Tell the user: the phase-1 ceiling, your intended briefing budget, and the
projected phase-3 ceiling at that budget. Get one go-ahead covering both rounds.

Default briefing budget: **12k tokens (~48k characters)**, which on a 5-model
panel prices phase 3 at roughly $0.29. The briefing is paid for *once per panel
model*, so its size is the dominant cost term — doubling the briefing doubles
that line. Honour `--budget USD` if the user passes one by sizing the briefing
to fit, not by trimming the panel.

Re-confirm later **only** if the actual phase-3 estimate exceeds what you quoted.

## Phase 1 — scope the evidence (cheap)

```
./scripts/or-panel.py -t 600 -o .panel/<slug>-scope --run [-p/-m …] \
  -s "Do not answer the question. List (a) what you would need to know to answer it well, (b) what kind of source would settle each point, and (c) any specific works, papers, projects, benchmarks or documentation worth consulting. Be concrete and prioritise. If you name a URL, mark it as recalled-from-memory rather than verified." \
  "<question>"
```

`-t 600` keeps this near-free. Then read `.panel/<slug>-scope.md`.

**Round 1 is a finding in itself.** If the models disagree about what the
question turns on, say so when you report back — that divergence is often more
useful than the eventual answers, and it costs almost nothing to obtain.

## Phase 2 — you do the research (free)

Take the union of what they asked for and satisfy it with WebSearch, WebFetch,
Read and Grep. This is the phase that costs nothing, so be thorough.

Rules that make the method work:

- **Treat named URLs as leads, not sources.** Models recall URLs badly and will
  produce confident dead links. Verify every one; search for the thing by name
  when the link is wrong. Note briefly which leads didn't resolve.
- **Correct for cutoff skew.** Their suggestions lean toward what they were
  trained on. Add current material on top, and date anything time-sensitive.
- **Cover the union, not the intersection.** A point only one model asked for is
  exactly the kind of thing prefetch-by-you would have missed.
- **Add anything obviously missing.** You are not limited to their list —
  especially repo or local context none of them can see.

Then write `.panel/<slug>-briefing.md`:

- **Neutral.** State findings, not conclusions. No recommendation, no framing
  that favours an answer. A briefing that argues a side anchors all five models
  and destroys the independence you are paying for.
- **Compressed.** Extracted passages and figures that bear on the question, not
  full-page dumps. Stay inside the budget; check with
  `./scripts/or-panel.py -f .panel/<slug>-briefing.md [-p/-m …] "<question>"`
  (no `--run`) and trim until the ceiling matches what you quoted.
- **Sourced and dated.** Every claim carries its origin and, where it matters,
  its date.
- **Marked for gaps.** Say plainly what you could not find. An unanswered need
  is information; silently omitting it is not.

## Phase 3 — the real round

```
./scripts/or-panel.py -f .panel/<slug>-briefing.md -o .panel/<slug>-answer --run [-p/-m …] "<question>"
```

## Phase 4 — synthesis

Read `.panel/<slug>-answer.md` and write the analysis, as in `/panel`: your own
conclusion first, then where they split and which argument is stronger, unique
points, and blind spots. Flag truncated or failed models.

Two things this flow lets you say that `/panel` cannot:

- **Whether the evidence moved anyone.** You know what each model said it needed
  in phase 1. If a model got exactly the evidence it asked for and still landed
  where it presumably started, that is worth noting. If it changed direction,
  more so.
- **Whether the briefing was the bottleneck.** If several models hedge on the
  same missing fact, the gap is in phase 2, not in them — say so, and offer to
  re-run phase 3 against an extended briefing rather than pretending the answer
  is settled.

Report the combined actual cost of both rounds. Keep all four artifacts
(`-scope.md`, `-briefing.md`, `-answer.md`, and the `.json` files) — the briefing
is reusable, so a follow-up question on the same topic can skip phases 1 and 2.

## Notes

- Pass the user's `-p`, `-m`, `-t` and other flags through to **both** rounds so
  the same panel scopes and answers. Never substitute your own model picks.
- Don't use `--online` here. Phase 2 is the retrieval step, and paying the models
  to search as well defeats the shared-evidence property.
- If you are running inside an `sbx` sandbox, WebFetch is blocked by the
  default-deny egress policy for most domains — phase 2 needs
  `sbx policy allow network --sandbox <name> <host>` per source, or run on the host.
