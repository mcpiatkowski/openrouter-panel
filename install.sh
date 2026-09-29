#!/usr/bin/env bash
# Install orpan on this Mac: the `orpan` command and the two Claude Code skills.
#
# The command is a symlink, so a change to src/orpan.py applies at once.
# The skills are copied, not linked. A sandbox mounts only its own workspace, so a
# symlink pointing into this repo is dangling there. Run this again after you edit
# a skill, and start a new sandbox to pick the copy up.
set -e

repo="$(cd "$(dirname "$0")" && pwd)"

ln -sf "$repo/src/orpan.py" "$HOME/.local/bin/orpan"
cp -R "$repo/skills/briefing" "$repo/skills/synthesis" "$HOME/.claude/skills/"

# A symlink with a relative target is created without complaint and is then dangling,
# which zsh reports as `command not found`. Printing the target shows it at once.
echo "orpan  -> $(readlink "$HOME/.local/bin/orpan")"
echo "skills -> $HOME/.claude/skills/{briefing,synthesis}"
