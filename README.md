# Orpan

## OpenRouter Panel

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

## Install

```bash
./install.sh
orpan -h
```

The script does two things. It links `src/orpan.py` into `~/.local/bin` as `orpan`, so an
edit to the script applies at once. It copies the two skills into `~/.claude/skills`, where
Claude Code finds them.

The skills are copied, not linked. A sandbox mounts only its own workspace directory, so a
symlink pointing into this repository is dangling inside it. Run `./install.sh` again after
you edit a skill, and start a new sandbox to pick the copy up.

If `orpan` is not found, check three things: that `~/.local/bin` is on your `PATH`, that
`ls -l ~/.local/bin/orpan` shows an absolute target, and - in zsh, which caches command
locations - that you ran `rehash` or opened a new terminal.

## Usage

Run from a workspace: any directory that holds a `questions/` folder. Every path is
relative to the working directory, and nothing is read from this repository.

Your first question:

```bash
mkdir -p ~/garden/questions/apple && cd ~/garden
echo "When should I prune an apple tree: in winter or in summer?" > questions/apple/question.md
orpan --topic apple --role scope
```

A good question for a panel is one where informed people disagree. Gardeners split on this
one: winter pruning shapes the tree, summer pruning slows its growth. A question with one
settled answer is cheaper to ask a single model.

Attach photographs with `--image`, once per file:

```bash
orpan \
    --role scope \
    --topic apple \
    --image images/apple/north.jpeg \
    --image images/apple/south.jpeg
```

### Workspaces

A workspace is any directory with a `questions/` folder in it. The tool is installed once
and run from whichever workspace the question belongs to:

```
~/garden/    questions/apple/…      images/apple/…      .orpan/apple/…
~/kitchen/   questions/sourdough/…  images/sourdough/…  .orpan/sourdough/…
```

Keep the questions out of this repository. This one is public, and a question can hold
anything - medical notes, private measurements, photographs. A workspace is its own git
repository, private when its subject is private. It is also the unit a sandbox mounts, so
one workspace is one sandbox, with its own memory and nothing from the others in it.

### Topics

A topic is the subject of a panel, and the only name you have to remember. It resolves
both ends of a run, inside the workspace you are in:

```
questions/apple/question.md    # in — the question, edited between rounds
questions/apple/scope.sh       # the run itself, kept with its subject
.orpan/apple/                  # out — every report and payload
```

Because the question is derived rather than named, a mistyped topic fails at once with
`No question at questions/appel/question.md`, instead of quietly starting a second
topic and writing a perfectly good report into it.

### Options

| Option | Meaning |
|---|---|
| `--topic NAME` | **Required.** The subject: `questions/<topic>/question.md` in, `.orpan/<topic>/` out |
| `-q`, `--question-file FILE` | Read the question from this file instead of the topic's |
| `-p`, `--preset {cheap,balanced,quality}` | Which panel to ask. Default `cheap` |
| `--role {answer,scope}` | Use a built-in system prompt |
| `-s`, `--system-prompt TEXT` | Use your own system prompt instead |
| `-i`, `--image PATH` | Attach an image. Repeat for more than one |
| `--refresh` | Accepted but does nothing — `fetch_catalog()` is not wired in yet |

`--topic` is required: every run belongs to a subject, and the subject is what makes the
reports findable afterwards. There is no way to pass a question on the command line — a
question you cannot edit and re-ask is not much use, and re-asking is the whole point.
`--role` and `--system-prompt` remain mutually exclusive.

The two built-in roles:

- **`scope`** — do not answer; list what you would need to know, what kind of source
  would settle each point, and which specific works are worth consulting.
- **`answer`** — answer using the supplied briefing as primary evidence, and say plainly
  where the briefing does not settle a point.

### Choosing the panel

Three panels, in `PRESETS` near the top of `src/orpan.py`:

```python
PRESETS: dict[str, tuple[str, ...]] = {
    "cheap": ("google/gemini-3.8-flash", "openai/gpt-5.6-luna", "z-ai/glm-5.3-flash"),
    "balanced": ("anthropic/claude-sonnet-5", "google/gemini-3.8-flash", …),
    "quality": ("anthropic/claude-opus-5", "google/gemini-3.8-flash", …),
}
```

`cheap` is the default, and it is the one to iterate a question against: a scope round
costs a few cents, so re-asking after every edit is affordable. Move to `-p quality` once
the question has stopped changing — for the last scope round and for the answer.

All models are asked concurrently, so a run takes as long as the slowest one rather than
the sum. Model IDs come from https://openrouter.ai/models.

## What you get

**On screen** — one block per model, then the panel totals:

```
google/gemini-3.8-flash  via Google  52s
  tokens   1334 in / 2583 out (1061 reasoning)
  cost     $0.0107   prompt $0.0010 + completion $0.0097

panel    2/3 answered  $0.0321
balance  $3.85
```

Everything a run produces lands under `.orpan/<topic>/`, so one subject is one directory
you can read, copy or delete as a unit:

```
.orpan/apple/
├── 20260913T090210Z.md            # no --role, no prefix
├── ANSWER-20260913T084023Z.md     # --role answer
├── SCOPE-20260913T081306Z.md      # --role scope
└── raw/
    ├── google-gemini-3.8-flash-20260913T090210Z.json
    └── moonshotai-kimi-k3-20260913T090210Z.json
```

**`.orpan/<topic>/<ROLE>-<timestamp>.md`** — the panel report. This is the file you feed
to the synthesiser. The role leads, in upper case, so runs of one kind sort together and
stand out from the bare timestamps of runs made without a `--role`. Within a role, the
timestamp sorts them by time.

**`.orpan/<topic>/raw/<model>-<timestamp>.json`** — the raw OpenRouter payload from each
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

**No example workspace in this repository.** The first question under Usage is the
example. A folder holding only a `question.md` would show nothing those three lines do
not. It would earn its place only with a real report in it, and a report costs money to
make and goes stale whenever the presets change.

**No `pyproject.toml`, and no `uv tool install`.** The script declares its dependencies
inline, in the PEP 723 block at the top. A package file would be a second place to declare
the same thing. A packaged install is only needed on a machine that does not have this
checkout; for one Mac with one checkout, a symlink does the whole job and an edit to
`src/orpan.py` takes effect without reinstalling. Revisit this if `orpan` ever has to run
inside a sandbox, because a sandbox mounts only its own workspace and cannot see this
repository.

**The skills are copied into `~/.claude/skills`, not linked.** Measured: the host directory
is passed into a sandbox with its symlinks unresolved, so a link into this repository is
dangling there — `.venv/bin/python` behaves the same way. The cost is two copies of each
skill and the need to run `./install.sh` again after editing one. The alternative, keeping
the skills only in `~/.claude/skills`, would leave the pipeline unversioned and separated
from the report format it depends on.

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

**No time limit on an answer.** `TIMEOUT` looks like one, but it is not: it is how long
the tool waits for the *next piece of data*, and every piece that arrives starts the count
again. A model that keeps sending can run far longer than 400 seconds —
`z-ai/glm-5.3-flash` took 459s on an answer round and returned a complete answer for
$0.0159. That is on purpose. A real time limit would cut a model off after it had already
spent most of its money thinking, and bill you in full for nothing, which is the same
mistake as `max_tokens` above. A connection that goes properly quiet still fails after 400
seconds, which is the case worth failing on.

## How it works

One request per model, all in flight at once, each turning into a `Response` whichever
way it goes:

```
Prompt ──> ask() ──> Response ──┐
Prompt ──> ask() ──> Response ──┼──> render_panel() ──> .orpan/<topic>/<stamp>.md
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
