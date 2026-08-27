#!/usr/bin/env bash
# or-fusion.sh — run OpenRouter's `openrouter:fusion` server tool from the CLI.
#
# A panel of models answers the prompt in parallel (each with web_search /
# web_fetch), an analyst model compares them into structured JSON, and an outer
# model writes the final answer from that analysis.
#
# SAFETY: this script NEVER spends money unless you pass --run. The default is a
# cost estimate only. Even with --run it aborts if the worst-case ceiling exceeds
# --max-spend or if the account balance is below --min-balance.
#
# Docs: https://openrouter.ai/docs/guides/features/server-tools/fusion

set -euo pipefail

API="https://openrouter.ai/api/v1"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/openrouter-models.json"
CACHE_MAX_AGE=86400

# ---------------------------------------------------------------- defaults ---
PRESET="balanced"
PANEL=""
ANALYST=""
OUTER=""
MAX_TOKENS=6000
MAX_TOOL_CALLS=3
REASONING=""
TEMPERATURE=""
CONTEXT_FILE=""
OUT_DIR=".fusion"
OUT_BASE=""
MAX_SPEND="1.50"
MIN_BALANCE="2.00"
DO_RUN=0
RAW_JSON=0
PRINT_BODY=0
FORCE_TOOL=1
QUESTION=""

# Preset panels. Model IDs verified against /api/v1/models.
preset_panel() {
  case "$1" in
    cheap)    echo "openai/gpt-5.4-mini,google/gemini-3.7-flash,deepseek/deepseek-v3.2" ;;
    balanced) echo "openai/gpt-5.2,google/gemini-3.1-pro-preview,x-ai/grok-4.6" ;;
    quality)  echo "openai/gpt-5.5,google/gemini-3.1-pro-preview,x-ai/grok-4.6,anthropic/claude-opus-4.8" ;;
    *) return 1 ;;
  esac
}
preset_analyst() {
  case "$1" in
    cheap)    echo "google/gemini-3.6-flash" ;;
    balanced) echo "anthropic/claude-opus-4.8" ;;
    quality)  echo "anthropic/claude-opus-4.8" ;;
    *) return 1 ;;
  esac
}

die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
note() { printf '\033[2m%s\033[0m\n' "$*" >&2; }

usage() {
  cat <<'EOF'
or-fusion.sh — multi-model deliberation via OpenRouter's fusion server tool

USAGE
  or-fusion.sh [options] "your research question"
  echo "question" | or-fusion.sh [options]

By default this only ESTIMATES cost and exits. Pass --run to actually spend.

OPTIONS
  -p, --preset NAME       cheap | balanced | quality        (default: balanced)
  -m, --models LIST       comma-separated panel, 1-8 models (overrides preset)
  -a, --analyst MODEL     model that produces the analysis JSON
      --outer MODEL       model that writes the final answer (default: analyst)
  -t, --max-tokens N      max_completion_tokens per inner call   (default: 6000)
  -c, --max-tool-calls N  web_search/web_fetch steps per model, 1-16 (default: 3)
  -r, --reasoning EFFORT  low | medium | high
      --temperature N     0-2, forwarded to panel calls only
  -f, --context FILE      prepend FILE's contents to the question
  -o, --out NAME          output basename        (default: .fusion/<timestamp>)
      --max-spend USD     abort if the ceiling exceeds this     (default: 1.50)
      --min-balance USD   abort if balance is below this        (default: 2.00)
      --no-force          let the outer model decide whether to call fusion
                          (default: tool_choice=required, always call it)
      --run               actually make the call and spend credits
      --json              print the raw API response to stdout
      --print-body        show the exact request JSON (works without --run)
  -h, --help              this text

PRESETS
  cheap     gpt-5.4-mini + gemini-3.7-flash + deepseek-v3.2, analyst gemini-3.6-flash
  balanced  gpt-5.2 + gemini-3.1-pro + grok-4.6, analyst claude-opus-4.8
  quality   gpt-5.5 + gemini-3.1-pro + grok-4.6 + claude-opus-4.8, analyst opus-4.8

CREDENTIALS
  $OPENROUTER_API_KEY if set, otherwise the macOS keychain item
  `security find-generic-password -s openrouter-api-key -w`.

EXAMPLES
  or-fusion.sh "Is SQLite a reasonable primary datastore for a 50k-user SaaS?"
  or-fusion.sh -p cheap --run "Compare uv, poetry and pdm for a new project"
  or-fusion.sh -m "openai/gpt-5.2,x-ai/grok-4.6" -t 3000 --run "..."
EOF
}

# -------------------------------------------------------------- arg parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--preset)        PRESET="${2:?}"; shift 2 ;;
    -m|--models)        PANEL="${2:?}"; shift 2 ;;
    -a|--analyst)       ANALYST="${2:?}"; shift 2 ;;
    --outer)            OUTER="${2:?}"; shift 2 ;;
    -t|--max-tokens)    MAX_TOKENS="${2:?}"; shift 2 ;;
    -c|--max-tool-calls) MAX_TOOL_CALLS="${2:?}"; shift 2 ;;
    -r|--reasoning)     REASONING="${2:?}"; shift 2 ;;
    --temperature)      TEMPERATURE="${2:?}"; shift 2 ;;
    -f|--context)       CONTEXT_FILE="${2:?}"; shift 2 ;;
    -o|--out)           OUT_BASE="${2:?}"; shift 2 ;;
    --max-spend)        MAX_SPEND="${2:?}"; shift 2 ;;
    --min-balance)      MIN_BALANCE="${2:?}"; shift 2 ;;
    --no-force)         FORCE_TOOL=0; shift ;;
    --run)              DO_RUN=1; shift ;;
    --json)             RAW_JSON=1; shift ;;
    --print-body)       PRINT_BODY=1; shift ;;
    -h|--help)          usage; exit 0 ;;
    -*)                 die "unknown option: $1 (try --help)" ;;
    *)                  QUESTION="${QUESTION:+$QUESTION }$1"; shift ;;
  esac
done

command -v jq   >/dev/null || die "jq is required"
command -v curl >/dev/null || die "curl is required"

[[ -n "$QUESTION" ]] || { [[ -t 0 ]] || QUESTION="$(cat)"; }
[[ -n "$QUESTION" ]] || die "no question given (try --help)"

if [[ -n "$CONTEXT_FILE" ]]; then
  [[ -r "$CONTEXT_FILE" ]] || die "cannot read context file: $CONTEXT_FILE"
  QUESTION="$(printf '%s\n\n---\n\n%s' "$(cat "$CONTEXT_FILE")" "$QUESTION")"
fi

if [[ -z "$PANEL" ]]; then
  PANEL="$(preset_panel "$PRESET")" || die "unknown preset: $PRESET (cheap|balanced|quality)"
fi
if [[ -z "$ANALYST" ]]; then
  ANALYST="$(preset_analyst "$PRESET")" || die "unknown preset: $PRESET"
fi
[[ -n "$OUTER" ]] || OUTER="$ANALYST"

IFS=',' read -r -a PANEL_ARR <<< "$PANEL"
(( ${#PANEL_ARR[@]} >= 1 && ${#PANEL_ARR[@]} <= 8 )) || die "panel must be 1-8 models, got ${#PANEL_ARR[@]}"
(( MAX_TOOL_CALLS >= 1 && MAX_TOOL_CALLS <= 16 )) || die "--max-tool-calls must be 1-16"

# ------------------------------------------------------------- credentials ---
resolve_key() {
  if [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
    printf '%s' "$OPENROUTER_API_KEY"; return
  fi
  if command -v security >/dev/null 2>&1; then
    security find-generic-password -s openrouter-api-key -w 2>/dev/null && return
  fi
  die "no API key: set \$OPENROUTER_API_KEY or add keychain item 'openrouter-api-key'"
}
KEY="$(resolve_key)"

api_get() { curl -sS --max-time 30 -H "Authorization: Bearer $KEY" "$API/$1"; }

# ------------------------------------------------------------ model prices ---
refresh_cache() {
  mkdir -p "$(dirname "$CACHE")"
  local age=$CACHE_MAX_AGE
  if [[ -f "$CACHE" ]]; then
    local mtime now
    mtime=$(stat -f %m "$CACHE" 2>/dev/null || stat -c %Y "$CACHE" 2>/dev/null || echo 0)
    now=$(date +%s)
    age=$(( now - mtime ))
  fi
  if (( age >= CACHE_MAX_AGE )); then
    note "refreshing model price cache…"
    curl -sS --max-time 60 "$API/models" -o "$CACHE.tmp" \
      && jq -e '.data | length > 0' "$CACHE.tmp" >/dev/null \
      && mv "$CACHE.tmp" "$CACHE" \
      || { rm -f "$CACHE.tmp"; [[ -f "$CACHE" ]] || die "could not fetch model list"; }
  fi
}
refresh_cache

# price MODEL FIELD -> per-token USD (falls back to a deliberately high guess)
price() {
  local v
  v=$(jq -r --arg m "$1" --arg f "$2" \
       '(.data[] | select(.id == $m) | .pricing[$f] // empty) // empty' "$CACHE" | head -1)
  if [[ -z "$v" || "$v" == "null" ]]; then
    case "$2" in
      prompt)     echo "0.000005" ;;
      completion) echo "0.000025" ;;
      *)          echo "0" ;;
    esac
    return
  fi
  echo "$v"
}
known_model() { jq -e --arg m "$1" '[.data[] | select(.id == $m)] | length > 0' "$CACHE" >/dev/null; }

# ------------------------------------------------------------ cost ceiling ---
Q_CHARS=${#QUESTION}
PROMPT_TOK=$(( Q_CHARS / 4 + 800 ))

UNKNOWN=()
for m in "${PANEL_ARR[@]}" "$ANALYST" "$OUTER"; do
  known_model "$m" || UNKNOWN+=("$m")
done

ceiling=$(
  {
    for m in "${PANEL_ARR[@]}"; do
      printf '%s %s %s %s %s\n' "$PROMPT_TOK" "$(price "$m" prompt)" "$MAX_TOKENS" "$(price "$m" completion)" \
        "$(awk -v w="$(price "$m" web_search)" -v n="$MAX_TOOL_CALLS" 'BEGIN{printf "%.10f", w*n}')"
    done
    # analyst reads every panel answer, worst case all at max length
    printf '%s %s %s %s %s\n' \
      "$(( PROMPT_TOK + ${#PANEL_ARR[@]} * MAX_TOKENS ))" "$(price "$ANALYST" prompt)" \
      "$MAX_TOKENS" "$(price "$ANALYST" completion)" 0
    # outer model reads the analysis and writes the final answer
    printf '%s %s %s %s %s\n' \
      "$(( PROMPT_TOK + MAX_TOKENS ))" "$(price "$OUTER" prompt)" \
      "$MAX_TOKENS" "$(price "$OUTER" completion)" 0
  } | awk '{t += $1*$2 + $3*$4 + $5} END {printf "%.4f", t}'
)

# ------------------------------------------------------------- preflight ----
bal_json="$(api_get credits)" || die "could not reach OpenRouter"
if ! jq -e '.data' >/dev/null 2>&1 <<<"$bal_json"; then
  die "credits lookup failed: $(jq -c '.error // .' <<<"$bal_json")"
fi
REMAIN=$(jq -r '(.data.total_credits - .data.total_usage)' <<<"$bal_json" | awk '{printf "%.2f", $1}')

hr() { printf '\033[2m%s\033[0m\n' "────────────────────────────────────────────────────────"; }
hr
printf '  question   %s\n' "$(printf '%.68s' "$QUESTION")$([[ ${#QUESTION} -gt 68 ]] && echo '…')"
printf '  panel      %s\n' "$(IFS=,; echo "${PANEL_ARR[*]}" | tr ',' '\n' | sed '2,$s/^/             /')"
printf '  analyst    %s\n' "$ANALYST"
printf '  outer      %s\n' "$OUTER"
printf '  budget     %s tok/call · %s tool steps\n' "$MAX_TOKENS" "$MAX_TOOL_CALLS"
hr
printf '  balance    $%s\n' "$REMAIN"
printf '  ceiling    $%s   \033[2m(worst case: every model maxes out)\033[0m\n' "$ceiling"
printf '  typical    $%s   \033[2m(~30%% of ceiling in practice)\033[0m\n' \
  "$(awk -v c="$ceiling" 'BEGIN{printf "%.4f", c*0.3}')"
hr

if (( ${#UNKNOWN[@]} )); then
  note "not in the model list, priced pessimistically: ${UNKNOWN[*]}"
fi

over_spend=$(awk -v c="$ceiling" -v m="$MAX_SPEND" 'BEGIN{print (c>m)?1:0}')
under_bal=$(awk -v r="$REMAIN" -v m="$MIN_BALANCE" 'BEGIN{print (r<m)?1:0}')

# ------------------------------------------------------------- the request ---
params=$(jq -n \
  --argjson models "$(printf '%s\n' "${PANEL_ARR[@]}" | jq -R . | jq -s .)" \
  --arg analyst "$ANALYST" \
  --argjson maxtok "$MAX_TOKENS" \
  --argjson calls "$MAX_TOOL_CALLS" \
  '{analysis_models: $models, model: $analyst,
    max_completion_tokens: $maxtok, max_tool_calls: $calls}')

[[ -n "$REASONING" ]]   && params=$(jq --arg e "$REASONING" '. + {reasoning: {effort: $e}}' <<<"$params")
[[ -n "$TEMPERATURE" ]] && params=$(jq --argjson t "$TEMPERATURE" '. + {temperature: $t}' <<<"$params")

body=$(jq -n \
  --arg model "$OUTER" \
  --arg q "$QUESTION" \
  --argjson params "$params" \
  --argjson force "$FORCE_TOOL" \
  '{model: $model,
    messages: [{role: "user", content: $q}],
    tools: [{type: "openrouter:fusion", parameters: $params}],
    usage: {include: true}}
   | if $force == 1 then . + {tool_choice: "required"} else . end')

if (( PRINT_BODY == 1 )); then
  printf '\n  \033[2mrequest body:\033[0m\n'
  jq . <<<"$body"
fi

if (( DO_RUN == 0 )); then
  printf '\n  \033[33mestimate only.\033[0m Re-run with \033[1m--run\033[0m to execute.\n\n'
  exit 0
fi
(( over_spend == 0 )) || die "ceiling \$$ceiling exceeds --max-spend \$$MAX_SPEND (lower -t, shrink the panel, or raise --max-spend)"
(( under_bal == 0 ))  || die "balance \$$REMAIN is below --min-balance \$$MIN_BALANCE"

stamp="$(date +%Y%m%d-%H%M%S)"
[[ -n "$OUT_BASE" ]] || { mkdir -p "$OUT_DIR"; OUT_BASE="$OUT_DIR/$stamp"; }
mkdir -p "$(dirname "$OUT_BASE")"

note "calling fusion — panel of ${#PANEL_ARR[@]}, this usually takes 1-3 minutes…"
http=$(curl -sS --max-time 900 -w '\n%{http_code}' \
  -X POST "$API/chat/completions" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -H "X-Title: or-fusion.sh" \
  -d "$body" -o "$OUT_BASE.json") || die "request failed"

if [[ "$http" != "200" ]]; then
  printf '\033[31mHTTP %s\033[0m\n' "$http" >&2
  jq -r '.error.message // .' "$OUT_BASE.json" >&2
  exit 1
fi

if jq -e '.error' "$OUT_BASE.json" >/dev/null 2>&1; then
  printf '\033[31mAPI error:\033[0m %s\n' "$(jq -r '.error.message' "$OUT_BASE.json")" >&2
  exit 1
fi

(( RAW_JSON == 1 )) && jq . "$OUT_BASE.json"

# ------------------------------------------------------------- render out ----
# The fusion tool result can surface in a few shapes; find it structurally.
fusion=$(jq -c 'first(.. | objects | select(has("responses") and (has("analysis") or has("status"))))' \
  "$OUT_BASE.json" 2>/dev/null || echo null)

{
  printf '# Fusion: %s\n\n' "$QUESTION"
  printf '_%s · panel: %s · analyst: %s_\n\n' "$stamp" "$(IFS=,; echo "${PANEL_ARR[*]}")" "$ANALYST"
  printf -- '---\n\n## Answer\n\n'
  jq -r '.choices[0].message.content // "(no content returned)"' "$OUT_BASE.json"

  if [[ "$fusion" != "null" && -n "$fusion" ]]; then
    jq -r '
      def bullets(x): (x // []) | map("- " + .) | join("\n");
      "\n\n---\n\n## Analysis\n",
      (if (.analysis.consensus // []) | length > 0
         then "\n### Consensus\n\n" + bullets(.analysis.consensus) else "" end),
      (if (.analysis.contradictions // []) | length > 0
         then "\n\n### Disagreements\n\n" + (.analysis.contradictions | map(
              "- **" + (.topic // "?") + "**\n" +
              ((.stances // []) | map("    - `" + (.model // "?") + "` — " + (.stance // "")) | join("\n"))
            ) | join("\n")) else "" end),
      (if (.analysis.unique_insights // []) | length > 0
         then "\n\n### Unique insights\n\n" + (.analysis.unique_insights | map(
              "- `" + (.model // "?") + "` — " + (.insight // "")) | join("\n")) else "" end),
      (if (.analysis.partial_coverage // []) | length > 0
         then "\n\n### Partial coverage\n\n" + (.analysis.partial_coverage | map(
              "- " + (.point // "") + " _(" + (((.models // []) | join(", "))) + ")_") | join("\n")) else "" end),
      (if (.analysis.blind_spots // []) | length > 0
         then "\n\n### Blind spots\n\n" + bullets(.analysis.blind_spots) else "" end),
      (if (.failed_models // []) | length > 0
         then "\n\n### Failed panel models\n\n" + (.failed_models | map("- " + (tostring)) | join("\n")) else "" end),
      (if (.responses // []) | length > 0
         then "\n\n---\n\n## Raw panel responses\n\n" + (.responses | map(
              "<details><summary><code>" + (.model // "?") + "</code></summary>\n\n" +
              (.content // "") + "\n\n</details>") | join("\n\n")) else "" end)
    ' <<<"$fusion"
  else
    printf '\n\n---\n\n_No structured fusion payload found in the response; see %s.json._\n' "$OUT_BASE"
  fi
} > "$OUT_BASE.md"

cost=$(jq -r '.usage.cost // empty' "$OUT_BASE.json")
hr
printf '  \033[32mdone\033[0m  %s.md\n' "$OUT_BASE"
[[ -n "$cost" ]] && printf '  cost   $%s   \033[2m(ceiling was $%s)\033[0m\n' \
  "$(awk -v c="$cost" 'BEGIN{printf "%.4f", c}')" "$ceiling"
printf '  left   $%s\n' "$(api_get credits | jq -r '(.data.total_credits - .data.total_usage)' | awk '{printf "%.2f", $1}')"
hr
