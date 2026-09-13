#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27"]
# ///
import argparse
import base64
import json
import mimetypes
import os
import sys
import time
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path

import httpx

TIMEOUT: float = 400.0
OR_API: str = "https://openrouter.ai/api/v1"
OR_MODEL_ID: str = "google/gemini-3.8-flash"

SYSTEM_PROMPTS: dict[str, str] = {
    "scope": (
        "Do not answer the question. List"
        "(a) what you would need to know to answer it well,"
        "(b) what kind of source would settle each point, and"
        "(c) any specific works, papers, projects, benchmarks or documentation worth consulting."
        "Be concrete and prioritise."
        "Don't give URLs."
    ),
    "answer": (
        "Answer the question using the briefing as your primary evidence."
        "Where the briefing settles a point, rely on it and say which part you are relying on."
        "Where it does not settle a point, say so explicitly rather than filling the gap from your own knowledge"
        "A marked gap is more useful to the reader than a confident guess."
        "If you believe the briefing is wrong or materially incomplete, say that too."
        "State your conclusion plainly, then your reasoning. Where you are uncertain,"
        "say how uncertain and what evidence would change your mind."
        "Do not hedge to cover both possibilities."
    ),
}


def image_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


@dataclass(frozen=True)
class Prompt:
    question: str
    system: str = ""
    images: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        for path in self.images:
            if not path.is_file():
                raise ValueError(f"No such image: {path}")

    @cached_property
    def data_urls(self) -> tuple[str, ...]:
        """Encoded once, reused for every panelist."""
        return tuple(image_data_url(p) for p in self.images)

    def to_messages(self) -> list[dict]:
        parts: list[dict] = [{"type": "text", "text": self.question}]
        parts += [{"type": "image_url", "image_url": {"url": url}} for url in self.data_urls]
        messages: list[dict] = [{"role": "user", "content": parts}]

        if self.system:
            messages.insert(0, {"role": "system", "content": self.system})

        return messages


@dataclass(frozen=True)
class Usage:
    """Tokens and dollars for one call."""

    upstream_completion_cost: float = 0.0
    upstream_prompt_cost: float = 0.0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    prompt_tokens: int = 0
    cost: float = 0.0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(**{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(self)})

    @classmethod
    def from_payload(cls, usage: dict) -> "Usage":
        completion = usage.get("completion_tokens_details") or {}
        costs = usage.get("cost_details") or {}

        return cls(
            upstream_completion_cost=float(costs.get("upstream_inference_completions_cost") or 0.0),
            upstream_prompt_cost=float(costs.get("upstream_inference_prompt_cost") or 0.0),
            reasoning_tokens=int(completion.get("reasoning_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            cost=float(usage.get("cost") or 0.0),
        )


def extract_reasoning(message: dict) -> str:
    """Reasoning text, from whichever field the provider used. Empty string if none."""
    if direct := (message.get("reasoning") or "").strip():
        return direct

    blocks = message.get("reasoning_details") or []
    parts = [(b.get("text") or "").strip() for b in blocks]
    return "\n\n".join(p for p in parts if p)


@dataclass(frozen=True)
class Response:
    """One model's answer, or its failure. Never raises — the panel keeps going."""

    model: str  # what we ASKED for; the panel's key
    usage: Usage = field(default_factory=Usage)
    error: str | None = None
    finish_reason: str = ""
    generation_id: str = ""  # look the true cost up later at /generation?id=
    served_model: str = ""  # what OpenRouter routed to; differs under :floor / :nitro
    reasoning: str = ""
    provider: str = ""  # who served it, e.g. "Google"
    content: str = ""
    seconds: float = 0.0
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def ok(self) -> bool:
        """The call worked. Says nothing about whether it answered."""
        return self.error is None

    @property
    def usable(self) -> bool:
        """A panelist actually participated. This is the gate not `ok`."""
        return self.ok and bool(self.content.strip())

    @property
    def truncated(self) -> bool:
        """Hit an output ceiling. With no max_tokens sent, that ceiling is the model's own."""
        return self.finish_reason == "length"

    @classmethod
    def from_payload(cls, model: str, payload: dict, seconds: float = 0.0) -> "Response":
        """The `model` is what we asked for. An error payload carries no model at all."""
        if error := payload.get("error"):
            return cls(error=f"{error.get('code')}: {error.get('message')}", seconds=seconds, model=model, raw=payload)

        choice = payload["choices"][0]
        message = choice.get("message") or {}
        return cls(
            model=model,
            usage=Usage.from_payload(payload.get("usage") or {}),
            finish_reason=choice.get("finish_reason") or "",
            served_model=payload.get("model") or "",
            provider=payload.get("provider") or "",
            generation_id=payload.get("id") or "",
            content=message.get("content") or "",
            reasoning=extract_reasoning(message),
            seconds=seconds,
            raw=payload,
        )


def resolve_key() -> str:
    if key := os.environ.get("OPENROUTER_API_KEY"):
        return key
    raise ValueError("OPENROUTER_API_KEY environment variable is not set.")


def fetch_balance(client: httpx.Client) -> float | None:
    """Remaining OpenRouter credit in USD, or None if the lookup failed."""
    try:
        response = client.get("/credits", timeout=30)
        response.raise_for_status()
        data = response.json()["data"]
        return float(data["total_credits"]) - float(data["total_usage"])
    except httpx.HTTPError as exc:
        print(f"balance lookup failed: {exc}", file=sys.stderr)
        return None


def fetch_catalog() -> dict:
    # print(catalog["data"][0])
    # gemini_models = [model["id"] for model in catalog["data"] if "gemini" in model["id"].lower()]
    # print(gemini_models)
    cache = Path.home() / ".cache/openrouter-models.json"

    if args.refresh or not cache.exists():
        response = httpx.get(f"{OR_API}/models")
        try:
            response.raise_for_status()
            cache.write_text(json.dumps(response.json()))
        except httpx.HTTPStatusError as exc:
            print(f"Error {exc.response.status_code} while requesting {exc.request.url}")

    return json.loads(cache.read_text())


def open_client() -> httpx.Client:
    """One client per run: the key is resolved once and the config lives in one place."""
    return httpx.Client(
        headers={"Authorization": f"Bearer {resolve_key()}", "X-Title": "orpan-dev"},
        base_url=OR_API,
        timeout=TIMEOUT,
    )


def summary(answer: Response, balance: float | None = None) -> str:
    if not answer.ok:
        return f"{answer.model}  failed after {answer.seconds:.0f}s\n  {answer.error}"

    u = answer.usage
    lines = [
        f"{answer.model}  via {answer.provider}  {answer.seconds:.0f}s",
        f"  tokens   {u.prompt_tokens} in / {u.completion_tokens} out ({u.reasoning_tokens} reasoning)",
        f"  cost     ${u.cost:.4f}   prompt ${u.upstream_prompt_cost:.4f} + completion ${u.upstream_completion_cost:.4f}",
    ]
    if not answer.usable:
        lines.append(
            f"  ! no answer — {u.completion_tokens} completion tokens "
            f"({u.reasoning_tokens} reasoning), none of them content"
        )
    elif answer.truncated:
        lines.append("  ! truncated at the model's output ceiling")
    if balance is not None:
        lines.append(f"  balance  ${balance:.2f}")
    return "\n".join(lines)


def ask(client: httpx.Client, model_id: str, prompt: Prompt) -> Response:
    """Ask one model. Every outcome comes back as a Response."""
    started = time.monotonic()
    try:
        response = client.post(
            "/chat/completions",
            json={"model": model_id, "messages": prompt.to_messages(), "usage": {"include": True}},
        )
    except httpx.TimeoutException:
        # str(exc) is empty on timeouts, so say it ourselves.
        return Response(model=model_id, error=f"Timed out after {TIMEOUT:.0f}s", seconds=time.monotonic() - started)
    except httpx.HTTPError as exc:
        return Response(model=model_id, error=f"{type(exc).__name__}: {exc}", seconds=time.monotonic() - started)

    seconds = time.monotonic() - started

    try:
        payload = response.json()
    except json.JSONDecodeError:
        return Response(model=model_id, error=f"HTTP {response.status_code}: non JSON body", seconds=seconds)

    return Response.from_payload(model_id, payload, seconds)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orpan")

    q_group = p.add_mutually_exclusive_group(required=True)
    q_group.add_argument("question", nargs="?", help="Question to the panel")
    q_group.add_argument("-q", "--question-file", type=Path, metavar="FILE")

    sys_group = p.add_mutually_exclusive_group()
    sys_group.add_argument("-s", "--system-prompt", help="Custom system prompt.")
    sys_group.add_argument("--role", choices=sorted(SYSTEM_PROMPTS), help="Use built in system prompt")

    p.add_argument("--refresh", action="store_true", help="Refresh the model cache")
    p.add_argument("-i", "--image", action="append", default=[], type=Path, metavar="PATH")
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()

    prompt = Prompt(
        question=args.question or args.question_file.read_text(encoding="utf-8"),
        system=SYSTEM_PROMPTS.get(args.role) or args.system_prompt or "",
        images=tuple(args.image),
    )

    with open_client() as client:
        answer = ask(client, OR_MODEL_ID, prompt)
        balance = fetch_balance(client)

    print(summary(answer, balance))
    print(answer.content if answer.usable else "(no answer)")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = Path("mvp/gemini-response") / f"response-{stamp}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if answer.raw:
        archive.write_text(json.dumps(answer.raw, indent=2, ensure_ascii=False))
