"""Grounded answer generation.

The prompt lists numbered sources `[n] <citation>` followed by the source text (with context neighbours merged).
Sources are numbered exactly as shown to the user, so `[n]` in the answer always means `hits[n - 1]`. When the
sources do not fit the token budget (`context_window - max_tokens - prompt overhead`), the lowest-ranked sources
lose their context neighbours first, then are dropped entirely; the first source is truncated as a last resort.

`LlamaCppGenerator` uses llama.cpp's `create_chat_completion`, so the chat template stored in the GGUF file (or
`llm.chat_format`) produces the right special tokens and stop sequences for any instruction-tuned model.
"""
from __future__ import annotations

import itertools
import re
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .retrieval import hit_text
from .types import Citation, Hit

SYSTEM_PROMPT = """You are Kovcheg, an offline reference assistant used in emergencies. Answer the question using ONLY the numbered sources provided.

Rules:
- Answer in the same language as the question.
- After every claim, cite the source(s) it comes from as [n], using the numbers of the sources, e.g. [1] or [2][3].
- Keep numbers, doses, units, names, codes and technical terms exactly as written in the sources.
- If the sources do not contain enough information, say so plainly and do not guess. Never give instructions, doses or facts that the sources do not support.
- If sources disagree, say so and cite each.
- Be concise and practical: short paragraphs or numbered steps."""

USER_TEMPLATE = "Sources:\n\n{sources}\n\nQuestion: {question}\n\nAnswer with citations [n]:"
NO_CITATIONS_WARNING = "answer has no citations — verify against sources"
_TEMPLATE_MARGIN = 48          # tokens reserved for chat-template special tokens and role headers


def estimate_tokens(text: str) -> int:
    """Conservative token estimate when no tokenizer is available: ~4 chars/token for ASCII, ~2.5 for other scripts."""
    ascii_n = sum(1 for ch in text if ord(ch) < 128)
    return int(ascii_n / 4 + (len(text) - ascii_n) / 2.5) + 1


class Generator(Protocol):
    id: str
    context_window: int
    max_tokens: int

    def count_tokens(self, text: str) -> int: ...

    def stream(self, messages: list[dict[str, str]]) -> Iterator[str]: ...     # yields text deltas


# ---- prompt building ----------------------------------------------------------------------------------------------

def format_source(n: int, hit: Hit, *, with_context: bool = True, max_chars: int | None = None) -> str:
    text = hit_text(hit) if with_context else hit.chunk.text
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + " …"
    module = f" ({hit.chunk.module})" if hit.chunk.module else ""
    return f"[{n}] {hit.chunk.citation}{module}\n{text}"


@dataclass
class Prompt:
    messages: list[dict[str, str]]
    n_sources: int                         # sources given to the model: hits[:n_sources] are [1]..[n]
    tokens: int                            # estimated prompt tokens
    trimmed: list[str] = field(default_factory=list)   # notes about what did not fit


def build_prompt(question: str, hits: Sequence[Hit], *, context_window: int, max_tokens: int, count=estimate_tokens,
                 system: str = SYSTEM_PROMPT) -> Prompt:
    """Messages for a chat model with as many top-ranked sources as fit the budget."""
    budget = context_window - max_tokens - _TEMPLATE_MARGIN - count(system) - count(USER_TEMPLATE.format(sources="", question=question))
    full = [count(format_source(i + 1, h)) + 1 for i, h in enumerate(hits)]
    bare = [count(format_source(i + 1, h, with_context=False)) + 1 if h.context else full[i] for i, h in enumerate(hits)]
    use_ctx = [True] * len(hits)
    n = len(hits)
    trimmed: list[str] = []

    def total() -> int:
        return sum(full[i] if use_ctx[i] else bare[i] for i in range(n))

    while n > 0 and total() > budget:
        last = n - 1
        dropped_ctx = False
        for i in range(n - 1, -1, -1):          # lowest-ranked first: drop context neighbours
            if use_ctx[i] and hits[i].context:
                use_ctx[i] = False
                dropped_ctx = True
                break
        if dropped_ctx:
            continue
        if n == 1:
            break
        n = last
    blocks = [format_source(i + 1, hits[i], with_context=use_ctx[i]) for i in range(n)]
    if n and total() > budget:                  # a single huge source: truncate it to the budget
        room = max(200, int(budget * 2.5)) if budget > 0 else 200
        blocks = [format_source(1, hits[0], with_context=False, max_chars=room)]
        while count(blocks[0]) > max(budget, 50) and room > 200:
            room = int(room * 0.8)
            blocks = [format_source(1, hits[0], with_context=False, max_chars=room)]
        trimmed.append("source [1] was truncated to fit the model's context window")
    if n < len(hits):
        trimmed.append(f"only {n} of {len(hits)} sources fit the model's context window")
    if any(not use_ctx[i] and hits[i].context for i in range(n)):
        trimmed.append("some sources were given to the model without their neighbouring passages")
    user = USER_TEMPLATE.format(sources="\n\n".join(blocks), question=question.strip())
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return Prompt(messages, n, count(system) + count(user) + _TEMPLATE_MARGIN, trimmed)


# ---- citations ----------------------------------------------------------------------------------------------------

_CITE = re.compile(r"\[(\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*)\]")


def cited_numbers(text: str) -> list[int]:
    """Citation numbers in order of first appearance; handles [1], [1, 2], [1-3], [1][2]."""
    out: list[int] = []
    for m in _CITE.finditer(text):
        for part in re.split(r"\s*[,;]\s*", m.group(1)):
            if re.search(r"[–-]", part):
                a, b = (int(x) for x in re.split(r"\s*[–-]\s*", part)[:2])
                nums = list(range(a, b + 1)) if 0 <= b - a <= 20 else [a, b]
            else:
                nums = [int(part)]
            out.extend(x for x in nums if x not in out)
    return out


def check_citations(text: str, hits: Sequence[Hit], n_provided: int) -> tuple[list[Citation], list[str]]:
    """Citations of an answer and warnings: numbers outside 1..n_provided, or no citations at all."""
    cites = [Citation(n, 1 <= n <= n_provided, hits[n - 1] if 1 <= n <= n_provided else None) for n in cited_numbers(text)]
    warnings = []
    bad = [c.number for c in cites if not c.valid]
    if bad:
        warnings.append(f"answer cites source(s) {', '.join(f'[{b}]' for b in bad)} that do not exist "
                        f"(only {n_provided} were provided) — verify against sources")
    if text.strip() and not cites:
        warnings.append(NO_CITATIONS_WARNING)
    return cites, warnings


# ---- generators ---------------------------------------------------------------------------------------------------

class LlamaCppGenerator:
    """A local GGUF model through llama-cpp-python (lazy import; loads on construction)."""

    def __init__(self, model_path: str | Path, settings):
        model_path = Path(model_path)
        if not model_path.is_file():
            raise FileNotFoundError(f"LLM file not found: {model_path}")
        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise ImportError('the LLM needs the "llm" extra: pip install "kovcheg[llm]"') from e
        self.settings = settings
        self.id = model_path.name
        self.context_window = settings.context_window
        self.max_tokens = settings.max_tokens
        self._llm = Llama(model_path=str(model_path), n_ctx=settings.context_window, n_threads=settings.threads or None,
                          n_gpu_layers=settings.gpu_layers, chat_format=settings.chat_format or None,
                          use_mmap=True, use_mlock=False, verbose=False)
        self._merge_system = False
        self._lock = threading.Lock()

    def count_tokens(self, text: str) -> int:
        try:
            return len(self._llm.tokenize(text.encode("utf-8"), add_bos=False, special=False))
        except Exception:  # noqa: BLE001
            return estimate_tokens(text)

    @staticmethod
    def _merged(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """For chat templates without a system role (e.g. Gemma): prepend the system text to the first user turn."""
        sys = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [dict(m) for m in messages if m["role"] != "system"]
        if sys and rest:
            rest[0]["content"] = sys + "\n\n" + rest[0]["content"]
        return rest

    def stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        s = self.settings
        msgs = self._merged(messages) if self._merge_system else messages
        kwargs = dict(max_tokens=s.max_tokens, temperature=s.temperature, top_p=s.top_p, repeat_penalty=s.repeat_penalty, stream=True)
        with self._lock:
            try:
                it = self._llm.create_chat_completion(messages=msgs, **kwargs)
                first = next(it, None)
            except Exception as e:  # noqa: BLE001
                if self._merge_system or "system" not in str(e).lower():
                    raise
                self._merge_system = True
                it = self._llm.create_chat_completion(messages=self._merged(messages), **kwargs)
                first = next(it, None)
            if first is None:
                return
            for chunk in itertools.chain([first], it):
                delta = chunk["choices"][0].get("delta", {}).get("content")
                if delta:
                    yield delta


class EchoGenerator:
    """Model-free generator for tests and demos (`llm.model = "echo"`). Never use for real answers.

    Without a fixed `reply` it quotes the first sentence of source [1] and cites it.
    """

    id = "echo"

    def __init__(self, reply: str | None = None, *, context_window: int = 4096, max_tokens: int = 256, fail: Exception | None = None):
        self.reply, self.context_window, self.max_tokens, self.fail = reply, context_window, max_tokens, fail
        self.calls: list[list[dict[str, str]]] = []

    def count_tokens(self, text: str) -> int:
        return estimate_tokens(text)

    def stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        self.calls.append(messages)
        if self.fail is not None:
            raise self.fail
        text = self.reply
        if text is None:
            user = messages[-1]["content"]
            m = re.search(r"^\[1\] [^\n]*\n(.+?)(?:\n\n\[2\] |\n\nQuestion: )", user, re.S | re.M)
            first = re.split(r"(?<=[.!?])\s", m.group(1).strip(), maxsplit=1)[0] if m else ""
            text = f"{first} [1]" if first else "The sources do not contain an answer."
        yield from re.findall(r"\S+\s*", text)


def load_generator(settings) -> Generator | None:
    """Generator from `settings.llm`, or None in search-only mode. Raises if configured but unavailable."""
    m = settings.llm.model
    if not m:
        return None
    if m == "echo":
        return EchoGenerator(context_window=settings.llm.context_window, max_tokens=settings.llm.max_tokens)
    return LlamaCppGenerator(settings.path(m), settings.llm)
