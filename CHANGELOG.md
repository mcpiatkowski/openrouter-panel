# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-09-29

### Added

- `--web-search` lets each model search the web itself, through OpenRouter's
  `openrouter:web_search` server tool. Each model decides whether to search and what for.
- The report's summary table has a `searches` column, and a model's cost line gains a
  `+ search $…` part, so the search fees — often most of a round's cost — are visible.
- A `<sources>` block after each answer lists the pages that model cited.
- `-m`/`--models` takes preset names and OpenRouter model ids in any comma-separated mix,
  e.g. `-m cheap,x-ai/grok-4.6`. A model named twice is asked once, and a mistyped preset
  stops the run before any model is paid.
- `install.sh` links `orpan` into `~/.local/bin` and installs the `briefing` and
  `synthesis` Claude Code skills.

### Changed

- **Breaking:** reports and payloads are written to `.orpan/<topic>/` instead of
  `.panel/<topic>/`. Rename existing `.panel/` directories to keep old rounds with their
  topics. The script itself is now `src/orpan.py`.
- **Breaking:** `-m`/`--models` replaces `-p`/`--preset`; `-p quality` becomes `-m quality`.
- The `answer` role may now add knowledge from outside the briefing, provided it marks
  each such claim as its own and says how confident it is.
- The synthesis skill treats marked outside claims as leads for the next briefing to
  check, and unmarked ones as errors.
- The `cheap` preset adds `z-ai/glm-5.3-flash`. The `quality` preset is now
  `moonshotai/kimi-k3`, `openai/gpt-6-astra` and `x-ai/grok-4.6`.
- The `briefing` and `synthesis` skills moved from `.claude/commands/` to `skills/`.

### Removed

- The `willow` example question. Questions now live in a workspace outside this
  repository, and the README's first question serves as the example.

### Fixed

- The built-in `scope` and `answer` system prompts ran their sentences together with no
  space between them.
