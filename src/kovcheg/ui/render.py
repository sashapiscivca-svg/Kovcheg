"""Pure rendering helpers for the web interface (no Streamlit import, unit-testable).

Every string that comes from documents, module manifests, models or the user is HTML-escaped here; the Streamlit app
only passes the returned HTML to `st.markdown(..., unsafe_allow_html=True)`. Colours are translucent or semantic so
the page works with both the light and the dark Streamlit theme.
"""
from __future__ import annotations

import html
import re

from ..generation import NO_CITATIONS_WARNING
from ..rerank import sigmoid
from ..types import Hit

TEXTS: dict[str, dict[str, str]] = {
    "uk": {
        "title": "Ковчег",
        "subtitle": "Офлайн-довідник: відповіді лише з ваших документів, з посиланнями на джерела",
        "disclaimer": "Ковчег може помилятися. Перевіряйте відповідь за джерелами. У ситуаціях, що загрожують життю, "
                      "дійте за офіційними протоколами та викликайте екстрені служби (112, 103).",
        "modules": "Бази знань",
        "no_modules": "Немає жодної бази знань. Створіть її командою `kovcheg build НАЗВА`.",
        "docs": "док.",
        "valid": "підпис дійсний",
        "unsigned": "без підпису",
        "untrusted": "невідомий підписант",
        "invalid": "НЕДІЙСНА",
        "unknown": "не перевірено",
        "invalid_warning": "Цілісність бази «{name}» порушено: файли змінено або пошкоджено. Вона вимкнена; вмикайте, лише якщо довіряєте джерелу.",
        "module_error": "База «{name}» недоступна: {error}",
        "settings": "Налаштування",
        "language": "Мова інтерфейсу",
        "search_only": "Лише пошук (без мовної моделі)",
        "use_reranker": "Точне ранжування (реранкер)",
        "top_k": "Кількість джерел",
        "show_scores": "Показувати оцінки",
        "clear": "Очистити розмову",
        "reload": "Оновити бази",
        "status": "Стан системи",
        "encoder": "Семантичний пошук",
        "reranker": "Реранкер",
        "llm": "Мовна модель",
        "on": "увімкнено",
        "off": "вимкнено",
        "error": "помилка",
        "not_loaded": "не завантажено",
        "keyword_only": "лише пошук за ключовими словами",
        "loading": "Завантаження моделей…",
        "searching": "Шукаю в документах…",
        "ask": "Поставте питання…",
        "select_module": "Оберіть хоча б одну базу знань.",
        "no_evidence": "У вибраних базах немає відповіді на це питання. Ковчег не вгадуватиме.",
        "search_only_note": "Режим пошуку: нижче — найрелевантніші фрагменти документів.",
        "llm_unavailable": "Мовна модель недоступна — показую знайдені фрагменти.",
        "error_status": "Під час генерації сталася помилка — перевірте джерела нижче.",
        "no_citations": "Відповідь не містить посилань на джерела — перевірте її за джерелами.",
        "bad_citations": "Відповідь посилається на джерела, яких немає — перевірте її за джерелами.",
        "sources": "Джерела",
        "closest": "Найближчі фрагменти (низька релевантність)",
        "context": "сусідній текст",
        "relevance": "релевантність",
        "cited": "цитовано",
        "page": "с.",
        "details": "Технічні подробиці",
    },
    "en": {
        "title": "Kovcheg",
        "subtitle": "Offline reference: answers only from your documents, with sources",
        "disclaimer": "Kovcheg can be wrong. Check answers against the sources. In life-threatening situations follow "
                      "official protocols and call emergency services (112 / 911).",
        "modules": "Knowledge bases",
        "no_modules": "No knowledge bases yet. Create one with `kovcheg build NAME`.",
        "docs": "docs",
        "valid": "signature valid",
        "unsigned": "unsigned",
        "untrusted": "unknown signer",
        "invalid": "INVALID",
        "unknown": "not verified",
        "invalid_warning": "Integrity of “{name}” FAILED: its files were modified or damaged. It is disabled; enable it only if you trust the source.",
        "module_error": "“{name}” is unavailable: {error}",
        "settings": "Settings",
        "language": "Interface language",
        "search_only": "Search only (no language model)",
        "use_reranker": "Precise ranking (reranker)",
        "top_k": "Number of sources",
        "show_scores": "Show scores",
        "clear": "Clear conversation",
        "reload": "Reload knowledge bases",
        "status": "System status",
        "encoder": "Semantic search",
        "reranker": "Reranker",
        "llm": "Language model",
        "on": "on",
        "off": "off",
        "error": "error",
        "not_loaded": "not loaded",
        "keyword_only": "keyword search only",
        "loading": "Loading models…",
        "searching": "Searching the documents…",
        "ask": "Ask a question…",
        "select_module": "Select at least one knowledge base.",
        "no_evidence": "The selected knowledge bases contain no answer to this question. Kovcheg will not guess.",
        "search_only_note": "Search mode: the most relevant passages are shown below.",
        "llm_unavailable": "The language model is unavailable — showing the passages found.",
        "error_status": "Generation failed — check the sources below.",
        "no_citations": "The answer cites no sources — verify it against the sources.",
        "bad_citations": "The answer cites sources that do not exist — verify it against the sources.",
        "sources": "Sources",
        "closest": "Closest passages (low relevance)",
        "context": "surrounding text",
        "relevance": "relevance",
        "cited": "cited",
        "page": "p.",
        "details": "Technical details",
    },
}

LANGUAGES = {"uk": "Українська", "en": "English"}

CSS = """
<style>
.kv-src{border-left:3px solid rgba(0,140,220,.75);background:rgba(128,128,128,.08);padding:.6rem .8rem;margin:.45rem 0;border-radius:6px}
.kv-src .kv-head{font-weight:600}
.kv-src .kv-meta{opacity:.7;font-size:.82em;margin:.1rem 0 .35rem}
.kv-src .kv-text{white-space:pre-wrap;font-size:.93em;line-height:1.45}
.kv-src .kv-ctx{opacity:.62}
.kv-badge{display:inline-block;padding:0 .45em;border-radius:.7em;font-size:.75em;margin-left:.35em;border:1px solid currentColor;vertical-align:middle}
.kv-valid{color:#1f9d55}.kv-unsigned{color:#8a8a8a}.kv-untrusted{color:#d08700}.kv-unknown{color:#8a8a8a}
.kv-invalid{color:#fff;background:#d93025;border-color:#d93025;font-weight:700}
.kv-score{color:rgba(0,140,220,1)}
.kv-cite-bad{color:#d93025;font-weight:700}
</style>
"""


def t(lang: str, key: str, **kw: object) -> str:
    s = TEXTS.get(lang, TEXTS["uk"]).get(key) or TEXTS["en"].get(key, key)
    return s.format(**kw) if kw else s


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def integrity_badge(status: str, message: str, lang: str) -> str:
    status = status if status in ("valid", "unsigned", "untrusted", "invalid", "unknown") else "unknown"
    icon = {"valid": "✓ ", "invalid": "⚠ "}.get(status, "")
    return f'<span class="kv-badge kv-{status}" title="{esc(message)}">{icon}{esc(t(lang, status))}</span>'


def citation_label(hit: Hit, lang: str) -> str:
    c = hit.chunk
    s = c.doc_title or c.doc_path
    if c.page is not None:
        s += f", {t(lang, 'page')} {c.page}"
    if c.section:
        s += f" — {c.section}"
    return s


def source_card(n: int, hit: Hit, lang: str, *, show_scores: bool = False, cited: bool = False, max_chars: int = 1600) -> str:
    """HTML card for source [n]: location (title, page, section), module/path, escaped text and context."""
    c = hit.chunk
    badges = ""
    if cited:
        badges += f'<span class="kv-badge kv-valid">{esc(t(lang, "cited"))}</span>'
    rel = sigmoid(hit.rerank)
    if rel is not None:
        badges += f'<span class="kv-badge kv-score">{esc(t(lang, "relevance"))} {rel:.0%}</span>'
    if show_scores:
        parts = [f"{name} {v:.3f}" for name, v in (("fused", hit.score), ("dense", hit.dense), ("sparse", hit.sparse),
                                                     ("bm25", hit.bm25), ("rerank", hit.rerank)) if v is not None]
        badges += f'<span class="kv-badge kv-score">{esc(" · ".join(parts))}</span>'
    text = c.text if len(c.text) <= max_chars else c.text[:max_chars] + " …"
    before = [x for x in hit.context if x.idx < c.idx]
    after = [x for x in hit.context if x.idx > c.idx]
    ctx_b = "".join(f'<div class="kv-text kv-ctx">{esc(_short(x.text))}</div>' for x in before)
    ctx_a = "".join(f'<div class="kv-text kv-ctx">{esc(_short(x.text))}</div>' for x in after)
    return (f'<div class="kv-src"><div class="kv-head">[{n}] {esc(citation_label(hit, lang))}{badges}</div>'
            f'<div class="kv-meta">{esc(c.module)} · {esc(c.doc_path)}</div>'
            f'{ctx_b}<div class="kv-text">{esc(text)}</div>{ctx_a}</div>')


def _short(s: str, n: int = 400) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + " …"


_CITE = re.compile(r"\[(\d{1,3})\]")


def answer_markdown(text: str, n_valid: int) -> str:
    """Answer text safe for `st.markdown` (HTML disabled): escape HTML, neutralise images/links, flag invalid [n]."""
    s = html.escape(text, quote=False)
    s = s.replace("![", "!\\[").replace("](", "]\\(")
    return _CITE.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_valid else f"**[{m.group(1)}]⚠**", s)


def status_notice(status: str, lang: str) -> tuple[str, str] | None:
    """(kind, text) to show above the answer; kind is info | warning | error."""
    return {"no_evidence": ("warning", t(lang, "no_evidence")), "search_only": ("info", t(lang, "search_only_note")),
            "llm_unavailable": ("warning", t(lang, "llm_unavailable")), "error": ("error", t(lang, "error_status"))}.get(status)


def answer_warnings(warnings: list[str], lang: str) -> tuple[list[str], list[str]]:
    """Split engine warnings into (prominent localised messages, technical details)."""
    main, tech = [], []
    for w in warnings:
        if w == NO_CITATIONS_WARNING:
            main.append(t(lang, "no_citations"))
        elif w.startswith("answer cites source"):
            main.append(t(lang, "bad_citations"))
        else:
            tech.append(w)
    return main, tech


def model_status_line(status: dict, lang: str) -> str:
    """One line per model: on / off / error / not loaded (plain text, to be shown escaped)."""
    out = []
    for key in ("encoder", "reranker", "llm"):
        d = status.get(key) or {}
        state = d.get("state")
        if state == "loaded":
            v = f"{t(lang, 'on')} ({d.get('id') or d.get('configured')})"
        elif state == "error":
            v = f"{t(lang, 'error')}: {d.get('error')}"
        elif state == "disabled":
            v = t(lang, "off") + (f" — {t(lang, 'keyword_only')}" if key == "encoder" else "")
        else:
            v = t(lang, "not_loaded") + (f" ({d['error']})" if d.get("error") else "")
        out.append(f"{t(lang, key)}: {v}")
    return "\n".join(out)
