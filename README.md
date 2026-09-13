# orpan — an OpenRouter panel

Ask several models the same question at once. Each answers independently, with no
knowledge of the others. The tool collects the answers into one markdown file; a separate
step — usually Claude Code — reads that file and writes the synthesis.

The point of a panel is disagreement. If four models agree, that is weak evidence the
answer is right. If they disagree, the disagreement itself is the finding, and it is only
meaningful when none of them saw the others' work.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) — the script declares its own dependencies inline
- An OpenRouter API key in `OPENROUTER_API_KEY`

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
```

## Usage

Run from the repository root. Output paths are relative to the working directory.

```bash
# a question on the command line
uv run mvp/panel.py --topic wierzby "Czy przycięcie wierzb na 1.5m ich nie zabije?"

# a question from a file, with a built-in role and two photographs
uv run mvp/panel.py \
    --role scope \
    --topic willow \
    --question-file mvp/willow.md \
    --image images/small/polnoc_3.jpeg \
    --image images/small/kwiatostan_1.jpeg
```

### Options

| Option | Meaning |
|---|---|
| `question` | The question, as a positional argument |
| `-q`, `--question-file FILE` | Read the question from a file instead |
| `--topic NAME` | **Required.** The directory under `.panel/` this run belongs to |
| `--role {answer,scope}` | Use a built-in system prompt |
| `-s`, `--system-prompt TEXT` | Use your own system prompt instead |
| `-i`, `--image PATH` | Attach an image. Repeat for more than one |
| `--refresh` | Accepted but does nothing — `fetch_catalog()` is not wired in yet |

A question is required: give either the positional argument or `--question-file`, not
both. The same applies to `--role` and `--system-prompt`. A `--topic` is required too —
every run belongs to a subject, and naming it is how the reports stay findable.

The two built-in roles:

- **`scope`** — do not answer; list what you would need to know, what kind of source
  would settle each point, and which specific works are worth consulting.
- **`answer`** — answer using the supplied briefing as primary evidence, and say plainly
  where the briefing does not settle a point.

### Choosing the panel

Edit `OR_MODELS` near the top of `mvp/panel.py`:

```python
OR_MODELS: tuple[str, ...] = (
    "google/gemini-3.8-flash",
    "openai/gpt-5.6-luna",
    "z-ai/glm-5.3",
)
```

All models are asked concurrently, so the run takes as long as the slowest one rather
than the sum. Model IDs come from https://openrouter.ai/models.

## What you get

**On screen** — one block per model, then the panel totals:

```
google/gemini-3.8-flash  via Google  52s
  tokens   1334 in / 2583 out (1061 reasoning)
  cost     $0.0107   prompt $0.0010 + completion $0.0097

panel    2/3 answered  $0.0321
balance  $3.85
```

Everything a run produces lands under `.panel/<topic>/`, so one subject is one directory
you can read, copy or delete as a unit:

```
.panel/willow/
├── 20260913T090210Z.md            # no --role, no prefix
├── ANSWER-20260913T084023Z.md     # --role answer
├── SCOPE-20260913T081306Z.md      # --role scope
└── raw/
    ├── google-gemini-3.8-flash-20260913T090210Z.json
    └── moonshotai-kimi-k3-20260913T090210Z.json
```

**`.panel/<topic>/<ROLE>-<timestamp>.md`** — the panel report. This is the file you feed
to the synthesiser. The role leads, in upper case, so runs of one kind sort together and
stand out from the bare timestamps of runs made without a `--role`. Within a role, the
timestamp sorts them by time.

**`.panel/<topic>/raw/<model>-<timestamp>.json`** — the raw OpenRouter payload from each
model, kept so the parser can be tested against real responses. The timestamp is what ties
a payload back to its report.

## Reading the report

The report has one title, a summary table, the full question, and one block per model:

```markdown
<panelist model="google/gemini-3.8-flash" status="answered">

...the model's answer...

</panelist>
```

The `status` attribute is the part that matters. A model can be billed in full and still
return nothing, so absence of text does not mean absence of opinion:

| status | meaning |
|---|---|
| `answered` | The model replied normally. Use the answer. |
| `truncated` | The model hit its output limit mid-answer. The text is real but incomplete. |
| `no-answer` | The call succeeded and was billed, but no text came back. **This model did not participate.** Do not read its silence as agreement. |
| `failed` | The request never produced a response. The reason is in the block. |

Reasoning is included only for models that did not answer, where it is the only thing the
money bought. For models that answered, the reasoning is left out on purpose: it is the
model's working, it often contains ideas the model went on to reject, and it adds about a
third again to the length of every answer.

## Deliberate omissions

These are choices, not gaps. Please do not "fix" them without reading this section.

**No cost estimate before the run.** How much a model will spend on reasoning cannot be
known before it reasons, and image tokens vary by provider. An earlier version estimated
a worst case and then multiplied it by a fudge factor, which is a confession that the
number meant nothing. The `usage` figures reported after the call are exact, and replace it.

**No spending limits.** There is no `--max-spend` and no minimum-balance check. The tool
asks the question and waits.

**No `max_tokens`.** Capping the output was the tool's most expensive mistake. A
reasoning model spends its budget thinking first and answering last, so a cap that runs
out mid-thought bills for every token and returns an empty answer. An audit of earlier
runs found 9 of 30 responses came back with no content at all, at a cost of about $0.66
out of $2.70 — roughly a quarter of everything spent. Leaving `max_tokens` unset lets each
model run to its own ceiling, and `status="no-answer"` reports it when that still is not enough.

## How it works

One request per model, all in flight at once, each turning into a `Response` whichever
way it goes:

```
Prompt ──> ask() ──> Response ──┐
Prompt ──> ask() ──> Response ──┼──> render_panel() ──> .panel/<topic>/<stamp>.md
Prompt ──> ask() ──> Response ──┘
```

`ask()` never raises. Timeouts, connection failures, non-JSON bodies and API errors all
come back as a `Response` carrying an `error`, so one model's failure cannot take the
others' answers with it.

`Response` has three derived properties, and the distinction between the first two is the
one to understand:

- **`ok`** — the HTTP call worked. It says nothing about whether the model answered.
- **`usable`** — there is actually text to read. **This is the gate**, not `ok`.
- **`truncated`** — the model stopped because it ran out of output tokens.

Images are base64-encoded once and reused by every model in the panel.

Pressing Ctrl-C exits with status 130.
