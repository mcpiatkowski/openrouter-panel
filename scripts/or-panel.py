#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27"]
# ///
"""or-panel — ask several OpenRouter models the same question, in parallel.

Claude Code stays the orchestrator and the analyst; OpenRouter is billed only
for the panel's raw opinions. That removes ~68% of the full-fusion ceiling.

SAFETY: never spends unless you pass --run. Guards on --max-spend and
--min-balance abort before any billable request is made.

    ./scripts/or-panel.py "question"              # estimate only
    ./scripts/or-panel.py --run "question"        # actually ask the panel
    ./scripts/or-panel.py -f notes.md --run "..." # give the panel context

Python rewrite of scripts/legacy-sh/or-panel.sh — same flags, same cost
formula, same output schema, plus retries, per-model timeouts and live
progress.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

API = "https://openrouter.ai/api/v1"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "openrouter-models.json"
CACHE_MAX_AGE = 86_400

# Pessimistic fallbacks for models missing from the catalog, per token.
FALLBACK_PROMPT = 5e-6
FALLBACK_COMPLETION = 25e-6

# Exa "auto" web search, per request, plus extra results beyond 10.
WEB_BASE_COST = 0.007
WEB_EXTRA_RESULT_COST = 0.001

TYPICAL_FRACTION = 0.35  # observed share of the worst-case ceiling

PRESETS: dict[str, list[str]] = {
    "cheap": ["openai/gpt-5.4-mini", "google/gemini-3.7-flash", "deepseek/deepseek-v3.2"],
    "balanced": [
        "anthropic/claude-sonnet-5",
        "google/gemini-3.7-flash",
        "openai/gpt-5.6-terra",
        "moonshotai/kimi-k3",
        "x-ai/grok-4.6",
    ],
    # "balanced": ["openai/gpt-5.2", "google/gemini-3.1-pro-preview", "x-ai/grok-4.6"],
    "quality": [
        "openai/gpt-5.5",
        "google/gemini-3.1-pro-preview",
        "x-ai/grok-4.6",
        "anthropic/claude-opus-4.8",
    ],
    "diverse": [
        "openai/gpt-5.2",
        "google/gemini-3.1-pro-preview",
        "x-ai/grok-4.6",
        "deepseek/deepseek-v3.2",
    ],
}

RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


# ----------------------------------------------------------------- output ---
_COLOR = sys.stderr.isatty()

# https://no-color.org/
# _NO_COLOR = bool(os.environ.get("NO_COLOR"))
# _COLOR_OUT = sys.stdout.isatty() and not _NO_COLOR
# _COLOR_ERR = sys.stderr.isatty() and not _NO_COLOR


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def dim(t: str) -> str:
    return _c("2", t)


def red(t: str) -> str:
    return _c("31", t)


def green(t: str) -> str:
    return _c("32", t)


def yellow(t: str) -> str:
    return _c("33", t)


def bold(t: str) -> str:
    return _c("1", t)


def note(msg: str) -> None:
    print(dim(msg), file=sys.stderr)


def die(msg: str) -> None:
    print(f"{red('error:')} {msg}", file=sys.stderr)
    raise SystemExit(1)


def hr() -> None:
    print(dim("─" * 56))


# ------------------------------------------------------------ credentials ---
def resolve_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", "openrouter-api-key", "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    die("no API key: set $OPENROUTER_API_KEY or add keychain item 'openrouter-api-key'")
    raise AssertionError("unreachable")


# --------------------------------------------------------------- catalog ----
class Catalog:
    """The OpenRouter model list, cached on disk for a day."""

    def __init__(self, models: dict[str, dict]) -> None:
        self.models = models

    @classmethod
    def load(cls, refresh: bool = True) -> "Catalog":
        fresh = CACHE.exists() and (time.time() - CACHE.stat().st_mtime) < CACHE_MAX_AGE
        if refresh and not fresh:
            note("refreshing model price cache…")
            try:
                r = httpx.get(f"{API}/models", timeout=60)
                r.raise_for_status()
                data = r.json()
                if not data.get("data"):
                    raise ValueError("empty model list")
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                tmp = CACHE.with_suffix(".tmp")
                tmp.write_text(json.dumps(data))
                tmp.replace(CACHE)
            except Exception as exc:  # noqa: BLE001 - fall back to a stale cache
                if not CACHE.exists():
                    die(f"could not fetch model list: {exc}")
                note(f"using stale cache ({exc})")
        if not CACHE.exists():
            die("no model cache available")
        raw = json.loads(CACHE.read_text())
        return cls({m["id"]: m for m in raw.get("data", []) if "id" in m})

    def known(self, model: str) -> bool:
        return model in self.models

    def price(self, model: str, field_name: str) -> float:
        entry = self.models.get(model)
        if entry:
            value = (entry.get("pricing") or {}).get(field_name)
            if value not in (None, "", "null"):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        if field_name == "prompt":
            return FALLBACK_PROMPT
        if field_name == "completion":
            return FALLBACK_COMPLETION
        return 0.0


# ----------------------------------------------------------------- costs ----
def prompt_tokens(question: str, system: str) -> int:
    """Same heuristic as the shell version, so estimates stay comparable."""
    return (len(question) + len(system)) // 4 + 200


def web_cost(online: bool, web_results: int) -> float:
    if not online:
        return 0.0
    return WEB_BASE_COST + max(0, web_results - 10) * WEB_EXTRA_RESULT_COST


def ceiling_for(catalog: Catalog, panel: list[str], ptok: int, max_tokens: int, per_call_web: float) -> float:
    return sum(
        ptok * catalog.price(m, "prompt") + max_tokens * catalog.price(m, "completion") + per_call_web for m in panel
    )


# --------------------------------------------------------------- request ----
def build_body(model: str, args: argparse.Namespace, question: str) -> dict:
    messages: list[dict] = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": question})

    body: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": args.max_tokens,
        "usage": {"include": True},
    }
    if args.temperature is not None:
        body["temperature"] = args.temperature
    if args.reasoning:
        body["reasoning"] = {"effort": args.reasoning}
    if args.online:
        body["plugins"] = [{"id": "web", "max_results": args.web_results}]
    return body


@dataclass
class Result:
    model: str
    status: str = "error"
    content: str | None = None
    reasoning: str | None = None
    error: str | None = None
    finish: str | None = None
    cost: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempts: int = 1
    seconds: float = 0.0
    citations: list[str] = field(default_factory=list)

    @property
    def starved(self) -> bool:
        """Billed in full, but the whole budget went to reasoning before any answer.

        Reasoning models emit their chain of thought first and the answer last, so a
        completion that hits max_tokens mid-thought bills for every token and returns
        nothing. The fix is a higher -t, not a retry.
        """
        return self.status == "ok" and not (self.content or "").strip() and self.finish == "length"


def extract_reasoning(message: dict) -> str:
    """Reasoning text, from whichever field the provider used. Empty string if none."""
    direct = message.get("reasoning")
    if isinstance(direct, str) and direct.strip():
        return direct
    blocks = message.get("reasoning_details")
    if isinstance(blocks, list):
        parts = [
            b["text"] for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].strip()
        ]
        if parts:
            return "\n\n".join(parts)
    return ""


def parse_response(model: str, payload: dict, attempts: int, seconds: float) -> Result:
    """Turn one OpenRouter response into a Result. Pure — unit-testable."""
    if isinstance(payload.get("error"), dict):
        return Result(
            model=model,
            error=payload["error"].get("message") or "unknown API error",
            attempts=attempts,
            seconds=seconds,
        )
    choices = payload.get("choices") or []
    if not choices or "message" not in choices[0]:
        return Result(model=model, error="unparseable response", attempts=attempts, seconds=seconds)

    choice = choices[0]
    usage = payload.get("usage") or {}
    message = choice.get("message") or {}
    annotations = message.get("annotations") or []
    citations = [
        a["url_citation"]["url"]
        for a in annotations
        if isinstance(a, dict) and isinstance(a.get("url_citation"), dict) and a["url_citation"].get("url")
    ]
    return Result(
        model=model,
        status="ok",
        content=message.get("content") or "",
        reasoning=extract_reasoning(message) or None,
        finish=choice.get("finish_reason"),
        cost=float(usage.get("cost") or 0.0),
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        attempts=attempts,
        seconds=seconds,
        citations=citations,
    )


async def ask_one(client: httpx.AsyncClient, model: str, args: argparse.Namespace, question: str) -> Result:
    body = build_body(model, args, question)
    started = time.monotonic()
    last_error = "no attempt made"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = await client.post(f"{API}/chat/completions", json=body, timeout=args.timeout)
        except httpx.TimeoutException:
            last_error = f"timed out after {args.timeout}s"
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status_code == 200:
                try:
                    return parse_response(model, resp.json(), attempt, time.monotonic() - started)
                except json.JSONDecodeError:
                    last_error = "response was not JSON"
            elif resp.status_code in RETRY_STATUSES:
                last_error = f"HTTP {resp.status_code}"
                retry_after = resp.headers.get("retry-after")
                if attempt < MAX_ATTEMPTS:
                    delay = (
                        float(retry_after)
                        if retry_after and retry_after.replace(".", "", 1).isdigit()
                        else 2**attempt + random.uniform(0, 1)
                    )
                    note(f"  {model}: {last_error}, retrying in {delay:.1f}s")
                    await asyncio.sleep(delay)
                    continue
            else:
                # A non-retryable error: surface the API's own message.
                try:
                    payload = resp.json()
                    return parse_response(model, payload, attempt, time.monotonic() - started)
                except json.JSONDecodeError:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                break

        if attempt < MAX_ATTEMPTS and "timed out" not in last_error:
            await asyncio.sleep(2**attempt + random.uniform(0, 1))
        elif attempt < MAX_ATTEMPTS:
            continue
        else:
            break

    return Result(
        model=model,
        error=last_error,
        attempts=MAX_ATTEMPTS,
        seconds=time.monotonic() - started,
    )


async def run_panel(panel: list[str], args: argparse.Namespace, question: str, key: str) -> list[Result]:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "or-panel.py",
    }
    results: list[Result] = []
    limits = httpx.Limits(max_connections=len(panel) + 2)
    async with httpx.AsyncClient(headers=headers, limits=limits) as client:
        tasks = [asyncio.create_task(ask_one(client, m, args, question), name=m) for m in panel]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            if result.starved:
                note(
                    f"  {yellow('!')} {result.model}  ${result.cost:.4f}  "
                    f"{result.completion_tokens} tok  {result.seconds:.0f}s  "
                    f"{yellow('no answer — budget spent entirely on reasoning; raise -t')}"
                )
            elif result.status == "ok":
                flag = " (truncated)" if result.finish == "length" else ""
                note(
                    f"  {green('✓')} {result.model}  ${result.cost:.4f}  "
                    f"{result.completion_tokens} tok  {result.seconds:.0f}s{flag}"
                )
            else:
                note(f"  {red('✗')} {result.model}  {result.error}")
    order = {m: i for i, m in enumerate(panel)}
    results.sort(key=lambda r: order.get(r.model, 0))
    return results


# ---------------------------------------------------------------- render ----
def render_markdown(question: str, stamp: str, results: list[Result]) -> str:
    lines = [
        f"# Panel: {question.splitlines()[0] if question.strip() else question}",
        "",
        f"_{stamp} · {len(results)} models · synthesis pending (Claude Code)_",
        "",
        "Each answer below was produced independently, with no knowledge of the others.",
        "",
        "---",
    ]
    for r in results:
        if r.status == "ok":
            head = f"\n## `{r.model}` · ${r.cost:.4f}"
            if r.starved:
                head += " · **no answer**"
            elif r.finish == "length":
                head += " · **truncated**"
            if r.attempts > 1:
                head += f" · {r.attempts} attempts"
            lines.append(head)
            lines.append("")
            if r.starved:
                lines.append(
                    f"> Spent all {r.completion_tokens} completion tokens on reasoning and "
                    f"never reached an answer. Re-run this model with a higher `-t`."
                )
                if r.reasoning:
                    lines.append("")
                    lines.append("<details><summary>reasoning it got through</summary>")
                    lines.append("")
                    lines.append(r.reasoning)
                    lines.append("")
                    lines.append("</details>")
            else:
                lines.append(r.content or "_(empty response)_")
            if r.citations:
                lines.append("")
                lines.append("<details><summary>sources</summary>")
                lines.append("")
                lines.extend(f"- {u}" for u in r.citations)
                lines.append("")
                lines.append("</details>")
        else:
            lines.append(f"\n## `{r.model}` · **failed**")
            lines.append("")
            lines.append(f"> {r.error or 'unknown error'}")
        lines.append("")
    return "\n".join(lines) + "\n"


def starved_advice(starved: list[Result], max_tokens: int) -> str:
    """The re-run command for models that spent everything on reasoning. Pure."""
    wasted = sum(r.cost for r in starved)
    names = ",".join(r.model for r in starved)
    return (
        f"\n  {yellow(f'Billed ${wasted:.4f} for reasoning that never reached an answer.')}\n"
        f"  Re-run just these with a much higher budget:\n"
        f"    {dim(f'or-panel.py -t {max_tokens * 4} -m {names} …')}"
    )


# ------------------------------------------------------------------ cli -----
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="or-panel.py",
        description="Parallel second opinions from several OpenRouter models. "
        "Claude Code does the synthesis; OpenRouter is billed only for the panel.",
        epilog=(
            "By default this only ESTIMATES cost and exits. Pass --run to spend.\n\n"
            "WHY NOT --online: Claude Code already has WebSearch and WebFetch on your "
            "subscription at no marginal cost. Researching first and passing the "
            "findings via -f is cheaper than paying every panel model to search the "
            "same thing, and it puts all models on identical evidence — which makes "
            "their disagreement mean something.\n\n"
            "SIZING -t: reasoning models emit their chain of thought before the answer, "
            "so a budget that runs out mid-thought bills in full and returns nothing. "
            "Scoping rounds at -t 600 will silence them. Give any panel containing a "
            "reasoning model at least -t 8000, or expect to pay twice."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("question", nargs="*", help="the question to put to the panel")
    p.add_argument(
        "-p", "--preset", default="balanced", choices=sorted(PRESETS), help="panel preset (default: balanced)"
    )
    p.add_argument("-m", "--models", help="comma-separated panel, 1-8 models (overrides preset)")
    p.add_argument("-t", "--max-tokens", type=int, default=4000, help="max tokens per panel answer (default: 4000)")
    p.add_argument("-s", "--system", default="", help="system prompt sent to every model")
    p.add_argument("-f", "--context", help="prepend this file's contents to the question")
    p.add_argument("--temperature", type=float, help="0-2")
    p.add_argument("-r", "--reasoning", choices=["low", "medium", "high"], help="reasoning effort")
    p.add_argument("--online", action="store_true", help="give each model web search (+~$0.007/model, Exa auto)")
    p.add_argument("--web-results", type=int, default=5, help="results per search when --online (default: 5)")
    p.add_argument("--timeout", type=float, default=300, help="per-model seconds (default: 300)")
    p.add_argument("-o", "--out", help="output basename (default: .panel/<timestamp>)")
    p.add_argument("--max-spend", type=float, default=1.00, help="abort if the ceiling exceeds this (default: 1.00)")
    p.add_argument("--min-balance", type=float, default=2.00, help="abort if balance is below this (default: 2.00)")
    p.add_argument("--run", action="store_true", help="actually make the calls and spend credits")
    p.add_argument("--print-body", action="store_true", help="show one request body (works without --run)")
    p.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    return p


def resolve_panel(args: argparse.Namespace) -> list[str]:
    if args.models:
        panel = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        panel = list(PRESETS[args.preset])
    if not 1 <= len(panel) <= 8:
        die(f"panel must be 1-8 models, got {len(panel)}")
    return panel


def read_question(args: argparse.Namespace) -> str:
    question = " ".join(args.question).strip()
    if not question and not sys.stdin.isatty():
        question = sys.stdin.read().strip()
    if not question:
        die("no question given (try --help)")
    if args.context:
        path = Path(args.context)
        if not path.is_file():
            die(f"cannot read context file: {args.context}")
        question = f"{path.read_text().rstrip()}\n\n---\n\n{question}"
    return question


def fetch_balance(key: str) -> float:
    try:
        r = httpx.get(f"{API}/credits", headers={"Authorization": f"Bearer {key}"}, timeout=30)
        payload = r.json()
    except Exception as exc:  # noqa: BLE001
        die(f"could not reach OpenRouter: {exc}")
        raise AssertionError("unreachable")
    if "data" not in payload:
        die(f"credits lookup failed: {payload.get('error', payload)}")
    data = payload["data"]
    return float(data["total_credits"]) - float(data["total_usage"])


def main() -> int:
    args = build_parser().parse_args()

    if args.self_test:
        return self_test()

    if not 1 <= args.web_results <= 50:
        die("--web-results must be 1-50")
    if args.max_tokens < 1:
        die("--max-tokens must be positive")

    question = read_question(args)
    panel = resolve_panel(args)
    catalog = Catalog.load()
    key = resolve_key()

    ptok = prompt_tokens(question, args.system)
    per_call_web = web_cost(args.online, args.web_results)
    ceiling = ceiling_for(catalog, panel, ptok, args.max_tokens, per_call_web)
    unknown = [m for m in panel if not catalog.known(m)]
    balance = fetch_balance(key)

    preview = question.replace("\n", " ")
    hr()
    print(f"  question   {preview[:68]}{'…' if len(preview) > 68 else ''}")
    print(f"  panel      {panel[0]}")
    for m in panel[1:]:
        print(f"             {m}")
    print(f"  synthesis  {dim('Claude Code (subscription — not billed here)')}")
    print(f"  budget     {args.max_tokens} tok/answer · {'web search on' if args.online else 'no web search'}")
    hr()
    print(f"  balance    ${balance:.2f}")
    print(f"  ceiling    ${ceiling:.4f}   {dim('(worst case: every model maxes out)')}")
    print(
        f"  typical    ${ceiling * TYPICAL_FRACTION:.4f}   {dim(f'(~{TYPICAL_FRACTION:.0%} of ceiling in practice)')}"
    )
    hr()
    if unknown:
        note(f"not in the model list, priced pessimistically: {', '.join(unknown)}")

    if args.print_body:
        print(f"\n  {dim(f'request body ({panel[0]}):')}")
        print(json.dumps(build_body(panel[0], args, question), indent=2))

    if not args.run:
        print(f"\n  {yellow('estimate only.')} Re-run with {bold('--run')} to execute.\n")
        return 0

    if ceiling > args.max_spend:
        die(
            f"ceiling ${ceiling:.4f} exceeds --max-spend ${args.max_spend:.4f} "
            "(lower -t, shrink the panel, or raise --max-spend)"
        )
    if balance < args.min_balance:
        die(f"balance ${balance:.2f} is below --min-balance ${args.min_balance:.2f}")

    note(f"asking {len(panel)} models in parallel…")
    results = asyncio.run(run_panel(panel, args, question, key))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_base = Path(args.out) if args.out else Path(".panel") / stamp
    out_base.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "question": question,
        "timestamp": stamp,
        "results": [asdict(r) for r in results],
    }
    out_base.with_suffix(".json").write_text(json.dumps(payload, indent=2))
    out_base.with_suffix(".md").write_text(render_markdown(question, stamp, results))

    starved = [r for r in results if r.starved]
    ok = sum(1 for r in results if r.status == "ok" and not r.starved)
    spent = sum(r.cost for r in results)

    hr()
    print(f"  {green('done')}  {out_base}.md")
    print(f"  panel  {ok}/{len(panel)} answered")
    print(f"  cost   ${spent:.4f}   {dim(f'(ceiling was ${ceiling:.4f})')}")
    try:
        print(f"  left   ${fetch_balance(key):.2f}")
    except SystemExit:
        pass
    hr()
    for r in results:
        if r.status != "ok":
            print(f"  {yellow('⚠')} {r.model}: {r.error}")
    if starved:
        for r in starved:
            print(f"  {yellow('⚠')} {r.model}: no answer — all {r.completion_tokens} tokens went to reasoning")
        print(starved_advice(starved, args.max_tokens))
    return 0 if ok else 1


# ------------------------------------------------------------- self-test ----
def self_test() -> int:
    """Exercise the pure functions on synthetic payloads. Spends nothing."""
    failures: list[str] = []

    def check(label: str, got, want) -> None:
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    ok = parse_response(
        "openai/gpt-5.2",
        {
            "choices": [{"finish_reason": "stop", "message": {"content": "Yes, with caveats."}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 310, "cost": 0.0041},
        },
        attempts=1,
        seconds=1.0,
    )
    check("ok.status", ok.status, "ok")
    check("ok.cost", ok.cost, 0.0041)
    check("ok.content", ok.content, "Yes, with caveats.")

    trunc = parse_response(
        "x-ai/grok-4.6",
        {
            "choices": [{"finish_reason": "length", "message": {"content": "No. At 50k"}}],
            "usage": {"completion_tokens": 4000, "cost": 0.0512},
        },
        attempts=2,
        seconds=9.0,
    )
    check("trunc.finish", trunc.finish, "length")
    check("trunc.starved", trunc.starved, False)

    starved = parse_response(
        "anthropic/claude-sonnet-5",
        {
            "choices": [{"finish_reason": "length", "message": {"content": "", "reasoning": "Let me think…"}}],
            "usage": {"completion_tokens": 4000, "cost": 0.0732},
        },
        attempts=1,
        seconds=14.0,
    )
    check("starved.starved", starved.starved, True)
    check("starved.reasoning", starved.reasoning, "Let me think…")
    check("starved.status", starved.status, "ok")

    blank = parse_response(
        "moonshotai/kimi-k3",
        {"choices": [{"finish_reason": "stop", "message": {"content": "   "}}], "usage": {}},
        attempts=1,
        seconds=1.0,
    )
    check("blank.starved (finished cleanly)", blank.starved, False)
    check("blank.reasoning", blank.reasoning, None)

    check(
        "reasoning from details",
        extract_reasoning({"reasoning_details": [{"text": "step one"}, {"text": "step two"}]}),
        "step one\n\nstep two",
    )
    check("reasoning direct wins", extract_reasoning({"reasoning": "a", "reasoning_details": [{"text": "b"}]}), "a")
    check("reasoning absent", extract_reasoning({"content": "hi"}), "")
    check("reasoning blank string", extract_reasoning({"reasoning": "   "}), "")

    starved_md = render_markdown("q", "stamp", [starved])
    check("starved md flagged", "**no answer**" in starved_md, True)
    check("starved md keeps reasoning", "Let me think…" in starved_md, True)

    advice = starved_advice([starved], 4000)
    check("advice quadruples budget", "-t 16000" in advice, True)
    check("advice names the model", "-m anthropic/claude-sonnet-5" in advice, True)
    check("advice reports waste", "$0.0732" in advice, True)

    err = parse_response(
        "google/gemini-3.1-pro-preview",
        {"error": {"message": "Insufficient credits.", "code": 402}},
        attempts=1,
        seconds=0.2,
    )
    check("err.status", err.status, "error")
    check("err.error", err.error, "Insufficient credits.")

    junk = parse_response("some/model", {"unexpected": True}, attempts=1, seconds=0.1)
    check("junk.status", junk.status, "error")
    check("junk.error", junk.error, "unparseable response")

    cited = parse_response(
        "openai/gpt-5.2",
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "See sources.",
                        "annotations": [
                            {"url_citation": {"url": "https://example.com/a"}},
                            {"type": "other"},
                        ],
                    },
                }
            ],
            "usage": {"cost": 0.001},
        },
        attempts=1,
        seconds=1.0,
    )
    check("cited.citations", cited.citations, ["https://example.com/a"])

    check("web_cost off", web_cost(False, 5), 0.0)
    check("web_cost on/5", round(web_cost(True, 5), 6), 0.007)
    check("web_cost on/12", round(web_cost(True, 12), 6), 0.009)
    check("prompt_tokens", prompt_tokens("a" * 400, "b" * 400), 400)

    cat = Catalog(
        {
            "a/known": {"pricing": {"prompt": "0.000002", "completion": "0.000006"}},
            "a/nulls": {"pricing": {"prompt": None, "completion": ""}},
        }
    )
    check("price known", cat.price("a/known", "completion"), 6e-6)
    check("price missing", cat.price("a/absent", "completion"), FALLBACK_COMPLETION)
    check("price null field", cat.price("a/nulls", "prompt"), FALLBACK_PROMPT)
    check(
        "ceiling",
        round(ceiling_for(cat, ["a/known", "a/absent"], 1000, 1000, 0.0), 8),
        round(1000 * 2e-6 + 1000 * 6e-6 + 1000 * FALLBACK_PROMPT + 1000 * FALLBACK_COMPLETION, 8),
    )

    md = render_markdown("Is SQLite enough?", "20260823-120000", [ok, trunc, err, cited])
    for needle in (
        "## `openai/gpt-5.2` · $0.0041",
        "**truncated**",
        "· 2 attempts",
        "**failed**",
        "> Insufficient credits.",
        "<details><summary>sources</summary>",
        "- https://example.com/a",
    ):
        if needle not in md:
            failures.append(f"render: missing {needle!r}")

    if failures:
        print(red(f"{len(failures)} self-test failure(s):"))
        for f in failures:
            print(f"  - {f}")
        return 1
    print(green("self-test: all checks passed"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        raise SystemExit(130) from None
