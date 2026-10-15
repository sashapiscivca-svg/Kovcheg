"""Kovcheg web interface (Streamlit). Start with `kovcheg ui`; never import this module from library code.

One `Kovcheg` engine per process (st.cache_resource); the engine serialises model calls internally, so several
browser sessions (e.g. phones on the local network) can share it. All document text is HTML-escaped by `render`.
"""
from __future__ import annotations

import json
import os
import sys

import streamlit as st

from kovcheg.engine import Kovcheg, ModuleInfo
from kovcheg.types import Answer
from kovcheg.ui.render import (
    CSS,
    LANGUAGES,
    answer_markdown,
    answer_warnings,
    esc,
    integrity_badge,
    model_status_line,
    source_card,
    status_notice,
    t,
)


def _cli_home() -> str | None:
    argv = sys.argv[1:]
    if "--home" in argv:
        i = argv.index("--home")
        if i + 1 < len(argv):
            return argv[i + 1]
    return os.environ.get("KOVCHEG_HOME")


@st.cache_resource(show_spinner=False)
def get_engine(home: str | None, overrides: str) -> Kovcheg:
    k = Kovcheg.from_home(home, json.loads(overrides) if overrides else None)
    k.load_models()
    return k


@st.cache_data(show_spinner=False, ttl=30)
def _modules(_engine: Kovcheg, home: str, generation: int) -> list[ModuleInfo]:
    return _engine.modules()


def _render_sources(ans: Answer, lang: str, show_scores: bool) -> None:
    cited = {c.number for c in ans.citations if c.valid}
    title = t(lang, "closest") if ans.status == "no_evidence" else t(lang, "sources")
    with st.expander(f"{title} ({len(ans.hits)})", expanded=not ans.text):
        st.markdown("".join(source_card(i, h, lang, show_scores=show_scores, cited=i in cited) for i, h in enumerate(ans.hits, 1)),
                    unsafe_allow_html=True)


def _render_answer(ans: Answer, lang: str, show_scores: bool) -> None:
    notice = status_notice(ans.status, lang)
    if notice:
        getattr(st, notice[0])(notice[1])
    if ans.text:
        st.markdown(answer_markdown(ans.text, len(ans.hits)))
    main, tech = answer_warnings(ans.warnings, lang)
    for w in main:
        st.warning(w)
    if ans.hits:
        _render_sources(ans, lang, show_scores)
    if tech:
        with st.expander(t(lang, "details")):
            for w in tech:
                st.text(w)
            if ans.timings:
                st.text(" · ".join(f"{k} {v:.2f}s" for k, v in ans.timings.items()))


def main() -> None:
    st.set_page_config(page_title="Kovcheg", page_icon="🛟", layout="wide", initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)
    home, overrides = _cli_home(), os.environ.get("KOVCHEG_OVERRIDES", "")

    with st.spinner("…"):
        engine = get_engine(home, overrides)
    ss = st.session_state
    ss.setdefault("lang", engine.settings.ui.language if engine.settings.ui.language in LANGUAGES else "uk")
    ss.setdefault("messages", [])
    ss.setdefault("gen", 0)
    lang = ss.lang

    with st.sidebar:
        st.selectbox(t(lang, "language"), list(LANGUAGES), format_func=LANGUAGES.get, key="lang")
        lang = ss.lang
        st.header(t(lang, "modules"))
        mods = _modules(engine, str(engine.settings.home), ss.gen)
        selected: list[str] = []
        if not mods:
            st.info(t(lang, "no_modules"))
        for m in mods:
            if m.error:
                st.warning(t(lang, "module_error", name=m.name, error=m.error))
                continue
            st.markdown(f"**{esc(m.title or m.name)}** {integrity_badge(m.integrity, m.integrity_message, lang)}<br>"
                        f"<small>{esc(m.name)} · {m.documents} {esc(t(lang, 'docs'))}</small>", unsafe_allow_html=True)
            if m.integrity == "invalid":
                st.error(t(lang, "invalid_warning", name=m.name) + f"\n\n{m.integrity_message}")
            if st.checkbox(m.name, value=m.enabled_by_default, key=f"mod::{m.name}", label_visibility="collapsed"):
                selected.append(m.name)

        st.divider()
        st.subheader(t(lang, "settings"))
        has_llm = engine.generator is not None
        search_only = st.toggle(t(lang, "search_only"), value=not has_llm, disabled=not has_llm)
        use_rr = st.toggle(t(lang, "use_reranker"), value=engine.reranker is not None, disabled=engine.reranker is None)
        top_k = st.slider(t(lang, "top_k"), 3, 20, min(max(engine.settings.retrieval.top_k, 3), 20))
        show_scores = st.toggle(t(lang, "show_scores"), value=False)
        c1, c2 = st.columns(2)
        if c1.button(t(lang, "clear"), use_container_width=True):
            ss.messages = []
            st.rerun()
        if c2.button(t(lang, "reload"), use_container_width=True):
            engine.reload()
            ss.gen += 1
            st.rerun()

        st.divider()
        st.caption(t(lang, "status"))
        st.text(model_status_line(engine.status(verify=False), lang))

    st.title(t(lang, "title"))
    st.caption(t(lang, "subtitle"))
    st.warning(t(lang, "disclaimer"), icon="⚠️")

    for msg in ss.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.text(msg["content"])
            else:
                _render_answer(msg["answer"], lang, show_scores)

    question = st.chat_input(t(lang, "ask"))
    if not question:
        return
    if not selected:
        st.error(t(lang, "select_module"))
        return
    ss.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.text(question)
    with st.chat_message("assistant"):
        box = st.empty()
        final: Answer | None = None
        text = ""
        stream = engine.ask_stream(question, selected, top_k, search_only=search_only, use_reranker=use_rr)
        with st.spinner(t(lang, "searching")):
            first = next(stream, None)
        for item in (_chain(first, stream) if first is not None else stream):
            if isinstance(item, Answer):
                final = item
            else:
                text += item
                box.markdown(answer_markdown(text, top_k) + " ▌")
        box.empty()
        if final is not None:
            _render_answer(final, lang, show_scores)
            ss.messages.append({"role": "assistant", "answer": final})


def _chain(first, rest):
    yield first
    yield from rest


main()
