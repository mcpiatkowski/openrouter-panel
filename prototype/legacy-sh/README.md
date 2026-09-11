# Legacy shell implementations

Verbatim copies of the original bash scripts, kept as a rollback path.

| File | Status |
|---|---|
| `or-panel.sh` | **superseded** by `../or-panel.py` (Python + uv, 2026-08-23) |
| `or-fusion.sh` | **not superseded** — `../or-fusion.sh` is still the live `/fusion` implementation; this is a plain backup |

Both are functional as of the date they were copied. The Python rewrite keeps
the same CLI flags, the same cost-estimate formula, and the same `.panel/*.json`
output schema, so rolling back is:

```bash
cp scripts/legacy-sh/or-panel.sh scripts/or-panel.sh
# then point .claude/commands/panel.md back at or-panel.sh
#   allowed-tools: Bash(./scripts/or-panel.sh:*)
```
