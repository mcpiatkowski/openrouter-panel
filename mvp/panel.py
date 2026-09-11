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
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path

import httpx

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


def resolve_key() -> str:
    if key := os.environ.get("OPENROUTER_API_KEY"):
        return key
    raise ValueError("OPENROUTER_API_KEY environment variable is not set.")


def fetch_balance(key: str) -> float:
    """Remaining OpenRouter credit in USD."""
    r = httpx.get(f"{OR_API}/credits", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    data = r.json()["data"]
    return float(data["total_credits"]) - float(data["total_usage"])


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


def print_summary():
    print(f"Balance remaining: ${fetch_balance(resolve_key()):.2f}")
    usage = response.json()["usage"]["cost_details"]
    print(f"""
        Total cost: {usage["upstream_inference_cost"]}
        Prompt cost: {usage["upstream_inference_prompt_cost"]}
        Completion cost: {usage["upstream_inference_completions_cost"]}
    """)


def ask(model_id: str, prompt: Prompt):
    response = httpx.post(
        f"{OR_API}/chat/completions",
        headers={"Authorization": f"Bearer {resolve_key()}", "X-Title": "orpan-dev"},
        json={"model": model_id, "messages": prompt.to_messages(), "usage": {"include": True}},
        timeout=120,
    )
    response.raise_for_status()

    return response


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
        system=SYSTEM_PROMPTS.get(args.role) or args.system or "",
        images=tuple(args.image),
    )

    response = ask(OR_MODEL_ID, prompt)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    Path(f"tmp/gemini-response/response-{stamp}.json").write_text(
        json.dumps(response.json(), indent=2, ensure_ascii=False)
    )

    print_summary()
