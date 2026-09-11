#!/usr/bin/env bash
# or-panel.sh — ask several OpenRouter models the same question, in parallel.
#
# Unlike or-fusion.sh, this buys NOTHING but the panel opinions. There is no
# OpenRouter analyst and no OpenRouter outer model: Claude Code reads the panel
# output and does the comparison and the final answer itself, on your
# subscription. That removes ~68% of the fusion ceiling.
#
# SAFETY: never spends unless you pass --run. Same guards as or-fusion.sh.
#
#   or-panel.sh "question"                 # estimate only
#   or-panel.sh --run "question"           # actually ask the panel
#   or-panel.sh -f notes.md --run "..."    # give the panel gathered context

set -euo pipefail

API="https://openrouter.ai/api/v1"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/openrouter-models.json"
CACHE_MAX_AGE=86400

# ---------------------------------------------------------------- defaults ---
PRESET="balanced"
PANEL=""
MAX_TOKENS=4000
TEMPERATURE=""
REASONING=""
SYSTEM=""
CONTEXT_FILE=""
OUT_DIR=".panel"
OUT_BASE=""
MAX_SPEND="1.00"
MIN_BALANCE="2.00"
ONLINE=0
WEB_RESULTS=5
DO_RUN=0
PRINT_BODY=0
TIMEOUT=300
QUESTION=""

preset_panel() {
  case "$1" in
    cheap)    echo "openai/gpt-5.4-mini,google/gemini-3.7-flash,deepseek/deepseek-v3.2" ;;
    balanced) echo "openai/gpt-5.2,google/gemini-3.1-pro-preview,x-ai/grok-4.6" ;;
    quality)  echo "openai/gpt-5.5,google/gemini-3.1-pro-preview,x-ai/grok-4.6,anthropic/claude-opus-4.8" ;;
    diverse)  echo "openai/gpt-5.2,google/gemini-3.1-pro-preview,x-ai/grok-4.6,deepseek/deepseek-v3.2" ;;
    *) return 1 ;;
  esac
}

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
note() { printf '\033[2m%s\033[0m\n' "$*" >&2; }
hr()   { printf '\033[2m%s\033[0m\n' "────────────────────────────────────────────────────────"; }

usage() {
  cat <<'EOF'
or-panel.sh — parallel second opinions from several OpenRouter models

Claude Code stays the orchestrator and does the synthesis. OpenRouter is billed
only for the panel completions.

USAGE
  or-panel.sh [options] "your question"
  echo "question" | or-panel.sh [options]

By default this only ESTIMATES cost and exits. Pass --run to actually spend.

OPTIONS
  -p, --preset NAME       cheap | balanced | quality | diverse  (default: balanced)
  -m, --models LIST       comma-separated panel, 1-8 models (overrides preset)
  -t, --max-tokens N      max tokens per panel answer          (default: 4000)
  -s, --system TEXT       system prompt sent to every model
  -f, --context FILE      prepend FILE's contents to the question
      --temperature N     0-2
  -r, --reasoning EFFORT  low | medium | high
      --online            give each model web search (+~$0.007/model, Exa auto)
      --web-results N     results per search when --online       (default: 5)
      --timeout N         per-model seconds                      (default: 300)
  -o, --out NAME          output basename          (default: .panel/<timestamp>)
      --max-spend USD     abort if the ceiling exceeds this      (default: 1.00)
      --min-balance USD   abort if balance is below this         (default: 2.00)
      --run               actually make the calls and spend credits
      --print-body        show one request body (works without --run)
  -h, --help              this text

WHY NOT --online
  Claude Code already has WebSearch and WebFetch on your subscription, at no
  marginal cost. Researching first and passing the findings via -f is cheaper
  than paying every panel model to search the same thing, and it puts all the
  models on identical evidence — which makes their disagreement mean something.

CREDENTIALS
  $OPENROUTER_API_KEY if set, otherwise the macOS keychain item
  `security find-generic-password -s openrouter-api-key -w`.
EOF
}

# -------------------------------------------------------------- arg parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--preset)      PRESET="${2:?}"; shift 2 ;;
    -m|--models)      PANEL="${2:?}"; shift 2 ;;
    -t|--max-tokens)  MAX_TOKENS="${2:?}"; shift 2 ;;
    -s|--system)      SYSTEM="${2:?}"; shift 2 ;;
    -f|--context)     CONTEXT_FILE="${2:?}"; shift 2 ;;
    --temperature)    TEMPERATURE="${2:?}"; shift 2 ;;
    -r|--reasoning)   REASONING="${2:?}"; shift 2 ;;
    --online)         ONLINE=1; shift ;;
    --web-results)    WEB_RESULTS="${2:?}"; shift 2 ;;
    --timeout)        TIMEOUT="${2:?}"; shift 2 ;;
    -o|--out)         OUT_BASE="${2:?}"; shift 2 ;;
    --max-spend)      MAX_SPEND="${2:?}"; shift 2 ;;
    --min-balance)    MIN_BALANCE="${2:?}"; shift 2 ;;
    --run)            DO_RUN=1; shift ;;
    --print-body)     PRINT_BODY=1; shift ;;
    -h|--help)        usage; exit 0 ;;
    -*)               die "unknown option: $1 (try --help)" ;;
    *)                QUESTION="${QUESTION:+$QUESTION }$1"; shift ;;
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
  PANEL="$(preset_panel "$PRESET")" || die "unknown preset: $PRESET (cheap|balanced|quality|diverse)"
fi

IFS=',' read -r -a PANEL_ARR <<< "$PANEL"
(( ${#PANEL_ARR[@]} >= 1 && ${#PANEL_ARR[@]} <= 8 )) || die "panel must be 1-8 models, got ${#PANEL_ARR[@]}"

# ------------------------------------------------------------- credentials ---
resolve_key() {
  if [[ -n "${OPENROUTER_API_KEY:-}" ]]; then printf '%s' "$OPENROUTER_API_KEY"; return; fi
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
  local age=$CACHE_MAX_AGE mtime now
  if [[ -f "$CACHE" ]]; then
    mtime=$(stat -f %m "$CACHE" 2>/dev/null || stat -c %Y "$CACHE" 2>/dev/null || echo 0)
    now=$(date +%s); age=$(( now - mtime ))
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

price() {
  local v
  v=$(jq -r --arg m "$1" --arg f "$2" \
       '(.data[] | select(.id == $m) | .pricing[$f] // empty) // empty' "$CACHE" | head -1)
  if [[ -z "$v" || "$v" == "null" ]]; then
    case "$2" in prompt) echo "0.000005" ;; completion) echo "0.000025" ;; *) echo "0" ;; esac
    return
  fi
  echo "$v"
}
known_model() { jq -e --arg m "$1" '[.data[] | select(.id == $m)] | length > 0' "$CACHE" >/dev/null; }

# ------------------------------------------------------------ cost ceiling ---
PROMPT_TOK=$(( (${#QUESTION} + ${#SYSTEM}) / 4 + 200 ))
WEB_COST=0
(( ONLINE == 1 )) && WEB_COST=$(awk -v n="$WEB_RESULTS" 'BEGIN{printf "%.6f", 0.007 + (n>10 ? (n-10)*0.001 : 0)}')

UNKNOWN=()
for m in "${PANEL_ARR[@]}"; do known_model "$m" || UNKNOWN+=("$m"); done

ceiling=$(
  for m in "${PANEL_ARR[@]}"; do
    printf '%s %s %s %s %s\n' "$PROMPT_TOK" "$(price "$m" prompt)" \
      "$MAX_TOKENS" "$(price "$m" completion)" "$WEB_COST"
  done | awk '{t += $1*$2 + $3*$4 + $5} END {printf "%.4f", t}'
)

bal_json="$(api_get credits)" || die "could not reach OpenRouter"
jq -e '.data' >/dev/null 2>&1 <<<"$bal_json" \
  || die "credits lookup failed: $(jq -c '.error // .' <<<"$bal_json")"
REMAIN=$(jq -r '(.data.total_credits - .data.total_usage)' <<<"$bal_json" | awk '{printf "%.2f", $1}')

hr
printf '  question   %s\n' "$(printf '%.68s' "$QUESTION" | tr '\n' ' ')$([[ ${#QUESTION} -gt 68 ]] && echo '…')"
printf '  panel      %s\n' "$(printf '%s\n' "${PANEL_ARR[@]}" | sed '2,$s/^/             /')"
printf '  synthesis  \033[2mClaude Code (subscription — not billed here)\033[0m\n'
printf '  budget     %s tok/answer%s\n' "$MAX_TOKENS" \
  "$( (( ONLINE == 1 )) && printf ' · web search on' || printf ' · no web search')"
hr
printf '  balance    $%s\n' "$REMAIN"
printf '  ceiling    $%s   \033[2m(worst case: every model maxes out)\033[0m\n' "$ceiling"
printf '  typical    $%s   \033[2m(~35%% of ceiling in practice)\033[0m\n' \
  "$(awk -v c="$ceiling" 'BEGIN{printf "%.4f", c*0.35}')"
hr
(( ${#UNKNOWN[@]} )) && note "not in the model list, priced pessimistically: ${UNKNOWN[*]}"

# --------------------------------------------------------------- request ----
build_body() {
  local model="$1" body
  body=$(jq -n --arg model "$model" --arg q "$QUESTION" --argjson maxtok "$MAX_TOKENS" \
    '{model: $model, messages: [{role:"user", content:$q}],
      max_tokens: $maxtok, usage: {include: true}}')
  [[ -n "$SYSTEM" ]] && body=$(jq --arg s "$SYSTEM" \
    '.messages = ([{role:"system", content:$s}] + .messages)' <<<"$body")
  [[ -n "$TEMPERATURE" ]] && body=$(jq --argjson t "$TEMPERATURE" '. + {temperature:$t}' <<<"$body")
  [[ -n "$REASONING" ]]   && body=$(jq --arg e "$REASONING" '. + {reasoning:{effort:$e}}' <<<"$body")
  (( ONLINE == 1 ))       && body=$(jq --argjson n "$WEB_RESULTS" \
    '. + {plugins: [{id:"web", max_results:$n}]}' <<<"$body")
  printf '%s' "$body"
}

if (( PRINT_BODY == 1 )); then
  printf '\n  \033[2mrequest body (%s):\033[0m\n' "${PANEL_ARR[0]}"
  build_body "${PANEL_ARR[0]}" | jq .
fi

if (( DO_RUN == 0 )); then
  printf '\n  \033[33mestimate only.\033[0m Re-run with \033[1m--run\033[0m to execute.\n\n'
  exit 0
fi

over=$(awk -v c="$ceiling" -v m="$MAX_SPEND" 'BEGIN{print (c>m)?1:0}')
under=$(awk -v r="$REMAIN" -v m="$MIN_BALANCE" 'BEGIN{print (r<m)?1:0}')
(( over == 0 ))  || die "ceiling \$$ceiling exceeds --max-spend \$$MAX_SPEND (lower -t, shrink the panel, or raise --max-spend)"
(( under == 0 )) || die "balance \$$REMAIN is below --min-balance \$$MIN_BALANCE"

# ------------------------------------------------------------- fan out ------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

note "asking ${#PANEL_ARR[@]} models in parallel…"
i=0
for m in "${PANEL_ARR[@]}"; do
  (
    build_body "$m" > "$TMP/$i.req"
    curl -sS --max-time "$TIMEOUT" -X POST "$API/chat/completions" \
      -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
      -H "X-Title: or-panel.sh" \
      -d @"$TMP/$i.req" -o "$TMP/$i.res" 2>"$TMP/$i.err" || echo "curl failed" > "$TMP/$i.err"
  ) &
  i=$(( i + 1 ))
done
wait

# ------------------------------------------------------------- collect ------
stamp="$(date +%Y%m%d-%H%M%S)"
[[ -n "$OUT_BASE" ]] || { mkdir -p "$OUT_DIR"; OUT_BASE="$OUT_DIR/$stamp"; }
mkdir -p "$(dirname "$OUT_BASE")"

results="[]"
i=0
for m in "${PANEL_ARR[@]}"; do
  entry=$(jq -n --arg model "$m" '{model:$model, status:"error", error:"no response", content:null, cost:0}')
  if [[ -s "$TMP/$i.res" ]]; then
    if jq -e '.choices[0].message' "$TMP/$i.res" >/dev/null 2>&1; then
      entry=$(jq --arg model "$m" '{
        model: $model, status: "ok",
        content: (.choices[0].message.content // ""),
        finish: (.choices[0].finish_reason // null),
        cost: (.usage.cost // 0),
        prompt_tokens: (.usage.prompt_tokens // 0),
        completion_tokens: (.usage.completion_tokens // 0)
      }' "$TMP/$i.res")
    else
      entry=$(jq --arg model "$m" '{model:$model, status:"error",
        error: (.error.message // "unparseable response"), content:null, cost:0}' "$TMP/$i.res" \
        2>/dev/null || jq -n --arg model "$m" --arg e "$(head -c 300 "$TMP/$i.res")" \
        '{model:$model, status:"error", error:$e, content:null, cost:0}')
    fi
  elif [[ -s "$TMP/$i.err" ]]; then
    entry=$(jq -n --arg model "$m" --arg e "$(head -c 300 "$TMP/$i.err")" \
      '{model:$model, status:"error", error:$e, content:null, cost:0}')
  fi
  results=$(jq --argjson e "$entry" '. + [$e]' <<<"$results")
  i=$(( i + 1 ))
done

jq -n --arg q "$QUESTION" --arg ts "$stamp" --argjson r "$results" \
  '{question:$q, timestamp:$ts, results:$r}' > "$OUT_BASE.json"

{
  printf '# Panel: %s\n\n' "$(printf '%s' "$QUESTION" | head -1)"
  printf '_%s · %s models · synthesis pending (Claude Code)_\n\n' "$stamp" "${#PANEL_ARR[@]}"
  printf 'Each answer below was produced independently, with no knowledge of the others.\n\n---\n'
  jq -r '.results[] |
    "\n## `" + .model + "`" +
    (if .status == "ok"
       then " · $" + (.cost | tostring) +
            (if .finish == "length" then " · **truncated**" else "" end) + "\n\n" + .content
       else " · **failed**\n\n> " + (.error // "unknown error") end) + "\n"
  ' "$OUT_BASE.json"
} > "$OUT_BASE.md"

ok=$(jq '[.results[] | select(.status=="ok")] | length' "$OUT_BASE.json")
spent=$(jq '[.results[].cost] | add // 0' "$OUT_BASE.json" | awk '{printf "%.4f", $1}')

hr
printf '  \033[32mdone\033[0m  %s.md\n' "$OUT_BASE"
printf '  panel  %s/%s answered\n' "$ok" "${#PANEL_ARR[@]}"
printf '  cost   $%s   \033[2m(ceiling was $%s)\033[0m\n' "$spent" "$ceiling"
printf '  left   $%s\n' "$(api_get credits | jq -r '(.data.total_credits - .data.total_usage)' | awk '{printf "%.2f", $1}')"
hr
jq -r '.results[] | select(.status!="ok") | "  ⚠ " + .model + ": " + (.error // "?")' "$OUT_BASE.json"
exit 0
