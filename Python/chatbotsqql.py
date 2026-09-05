"""
Insurance chatbot — SQL only, Streamlit front end.

    streamlit run chatbotsqql.py

Every answer is a database lookup. Nothing is generated. All connection,
routing and query logic lives in chatbot_core.py (shared with the BI
dashboard's "Ask the data" page); this file only renders
chatbot_core.answer_question() as a chat widget.
"""

import streamlit as st

from chatbot_core import answer_question, load_age_range, load_slabs


def render_chat():
    """Render the chat UI. Callable standalone or embedded in another app
    (e.g. as a tab in a dashboard) once chatbot_core is importable."""

    slabs = load_slabs()
    slab_text = ", ".join(
        f"{s/10000000:g}Cr" if s >= 10000000 else f"{s/100000:g}L" for s in slabs)
    age_lo, age_hi = load_age_range()

    with st.expander("💬 Try asking", expanded=False):
        st.markdown("""
**Premiums**
- Premium for a 40 year old at 10L
- Cheapest cover at 5L for a 30 year old
- Compare ABHI and HDFC ERGO at 10L

**Policy terms**
- ABHI waiting period
- Room rent limit for Star Health
- Does Tata AIG cover maternity

**Company financials**
- ABHI GWP
- Solvency ratio for all insurers
- ICICI Lombard ROE

**Definitions**
- What does sum insured mean?
- What is a combined ratio?
        """)
        st.divider()
        st.caption(f"Cover slabs: {slab_text}")
        st.caption(f"Ages: {age_lo}–{age_hi}")
        st.caption("Tier 1 · individual cover unless a floater is asked for")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    def render_message(m):
        st.markdown(m["content"])
        if m.get("table") is not None:
            st.dataframe(m["table"], hide_index=True, use_container_width=True)
        if m.get("fig") is not None:
            st.plotly_chart(m["fig"], use_container_width=True)
        if m.get("sql") and m.get("answered"):
            with st.expander("The query behind this answer"):
                st.code(m["sql"], language="sql")

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            render_message(m)

    question = st.chat_input("Ask a question")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        result = answer_question(question)
        assistant_message = {
            "role": "assistant", "content": result["answer"],
            "table": result["table"], "fig": result["fig"],
            "sql": result["sql"], "answered": result["answered"],
        }
        with st.chat_message("assistant"):
            render_message(assistant_message)
        st.session_state.messages.append(assistant_message)


def main():
    st.set_page_config(page_title="Insurance Assistant", layout="wide")
    st.title("Health insurance assistant")
    st.caption("Every answer is a database lookup. Nothing here is generated.")
    render_chat()


if __name__ == "__main__":
    main()
