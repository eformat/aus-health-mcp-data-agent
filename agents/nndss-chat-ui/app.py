"""NNDSS Data Agent — Streamlit Chat UI.

Provides a web chat interface for the Australian Disease Surveillance
data agent. Renders <reasoning> blocks as expandable sections and
confidence cards with colour coding.
"""

import os
import re
import time

import streamlit as st
from openai import OpenAI

AGENT_URL = os.environ.get(
    "AGENT_URL", "http://nndss-data-agent-agent-template:8080"
)

st.set_page_config(
    page_title="NNDSS Data Agent",
    page_icon="🏥",
    layout="wide",
)

CONFIDENCE_COLOURS = {
    "HIGH": "#28a745",
    "MODERATE": "#ffc107",
    "LOW": "#dc3545",
}

EXAMPLE_QUESTIONS = [
    "What notifiable diseases do you have data for?",
    "How many influenza cases were notified in NSW in 2023?",
    "Which state had the highest salmonellosis notifications in 2022?",
    "What is the healthiest state to live in per-capita?",
    "Compare influenza and pneumococcal disease trends over the past 5 years",
    "What food poisoning cases were reported in Queensland last year?",
    "How does NNDSS collect influenza data compared to sentinel surveillance?",
]


def parse_response(content: str) -> dict:
    """Parse agent response into reasoning, answer, and confidence card."""
    reasoning = ""
    match = re.search(r"<reasoning>(.*?)</reasoning>", content, re.DOTALL)
    if match:
        reasoning = match.group(1).strip()
        content = content[: match.start()] + content[match.end() :]

    last_think_end = content.rfind("</think>")
    if last_think_end != -1:
        content = content[last_think_end + len("</think>"):]
    else:
        think_patterns = [
            r"^The user is asking",
            r"^I need to use",
            r"^I should use",
            r"^Let'?s check",
            r"^Let'?s call",
            r"^Let'?s make",
            r"^Let'?s formulate",
            r"^Parameters:",
            r"^Wait,",
            r"^Ready\.",
        ]
        lines = content.split("\n")
        first_real = 0
        in_thinking = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if any(re.match(p, stripped) for p in think_patterns):
                in_thinking = True
            elif in_thinking and stripped:
                if re.match(
                    r"^(\*\*|Based on|In 20|There were|#{1,3} |The NNDSS|"
                    r"According to|Australia|Queensland|NSW|Victoria)",
                    stripped,
                ):
                    first_real = i
                    break
        if in_thinking and first_real > 0:
            content = "\n".join(lines[first_real:])

    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    content = re.sub(r"</?think>", "", content)

    confidence_level = ""
    confidence_match = re.search(
        r"\*\*Data Confidence:\s*(HIGH|MODERATE|LOW)\*\*", content
    )
    if confidence_match:
        confidence_level = confidence_match.group(1)

    card = ""
    card_match = re.search(r"(---\n\*\*Data Confidence.*?---)", content, re.DOTALL)
    if card_match:
        card = card_match.group(1)
        content = content[: card_match.start()] + content[card_match.end() :]

    # Extract timing stats (appended by the UI after streaming)
    stats = ""
    stats_match = re.search(
        r"---\n\*\*Query:\*\*\s*([\d.]+s)\s*\|\s*\*\*Generation:\*\*\s*([\d.]+s)\s*\|\s*\*\*Total:\*\*\s*([\d.]+s)",
        content,
    )
    if stats_match:
        stats = (
            f"<b>Query:</b> {stats_match.group(1)} | "
            f"<b>Generation:</b> {stats_match.group(2)} | "
            f"<b>Total:</b> {stats_match.group(3)}"
        )
        content = content[: stats_match.start()] + content[stats_match.end() :]

    return {
        "reasoning": reasoning,
        "answer": content.strip(),
        "card": card,
        "confidence_level": confidence_level,
        "stats": stats,
    }


def render_response(content: str):
    """Render the agent response with styled sections."""
    parsed = parse_response(content)

    if parsed["reasoning"]:
        with st.expander("Reasoning", expanded=False, icon="🧠"):
            for line in parsed["reasoning"].split("\n"):
                line = line.strip()
                if not line:
                    continue
                if ":" in line:
                    key, _, value = line.partition(":")
                    st.markdown(f"**{key.strip()}:** {value.strip()}")
                else:
                    st.markdown(line)

    if parsed["answer"]:
        st.markdown(parsed["answer"])
    elif parsed["reasoning"] and not parsed["card"]:
        st.warning(
            "The agent ran out of tokens before completing its answer. "
            "Try a more specific question."
        )

    if parsed["card"] or parsed["stats"]:
        level = parsed["confidence_level"]
        colour = CONFIDENCE_COLOURS.get(level, "#6c757d")
        card_clean = parsed["card"].strip("-\n ") if parsed["card"] else ""
        stats_html = ""
        if parsed["stats"]:
            stats_html = (
                f'<div style="margin-top: 8px; padding-top: 8px; '
                f'border-top: 1px solid rgba(0,0,0,0.1); '
                f'font-size: 0.85em; color: #666;">'
                f'{parsed["stats"]}</div>'
            )
        st.markdown(
            f'<div style="border-left: 4px solid {colour}; '
            f'padding: 12px; margin: 16px 0; '
            f'background: rgba(0,0,0,0.03); border-radius: 4px;">'
            f"\n\n{card_clean}\n\n{stats_html}</div>",
            unsafe_allow_html=True,
        )


def call_agent(messages: list[dict]) -> str:
    """Call the agent (non-streaming for richer MLflow traces)."""
    client = OpenAI(base_url=f"{AGENT_URL}/v1", api_key="not-required")
    response = client.chat.completions.create(
        model="nndss-data-agent",
        messages=messages,
        stream=False,
        timeout=600,
    )
    return response.choices[0].message.content


# --- Session state ---

for key, default in [("messages", []), ("gen", 0)]:
    if key not in st.session_state:
        st.session_state[key] = default

# Handle clear via query param (survives full page reload)
if "clear" in st.query_params:
    st.session_state.messages = []
    st.session_state.gen += 1
    st.query_params.clear()

# --- Header ---

st.title("Australian Disease Surveillance Agent")
st.caption(
    "Ask questions about notifiable disease data from the NNDSS. "
    "Powered by structured reasoning over real surveillance data."
)

# --- Sidebar ---

with st.sidebar:
    st.header("Example Questions")
    for i, q in enumerate(EXAMPLE_QUESTIONS):
        if st.button(q, key=f"ex_{i}", use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": q})
            st.session_state.gen += 1
            st.rerun()

    st.divider()
    st.caption(f"Agent: `{AGENT_URL}`")
    # Use JS redirect to force a full page reload — this kills the
    # websocket and any in-flight API calls, which st.rerun() cannot do.
    st.markdown(
        '<a href="?clear=1" target="_self">'
        '<button style="width:100%;padding:8px 16px;background:#ff4b4b;'
        'color:white;border:none;border-radius:8px;cursor:pointer;'
        'font-size:16px;font-weight:600;">Clear Chat</button></a>',
        unsafe_allow_html=True,
    )

# --- Render chat history ---

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            render_response(msg["content"])
        else:
            st.markdown(msg["content"])

# --- Handle new chat input ---

if prompt := st.chat_input("Ask about Australian disease surveillance data..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.gen += 1
    st.rerun()

# --- Generate response if last message is user (no assistant reply yet) ---

if (
    st.session_state.messages
    and st.session_state.messages[-1]["role"] == "user"
):
    gen_at_start = st.session_state.gen
    with st.chat_message("assistant"):
        try:
            import time as _time
            t_start = _time.time()

            with st.status("Querying NNDSS data...", expanded=False) as status:
                content = call_agent(
                    [{"role": m["role"], "content": m["content"]}
                     for m in st.session_state.messages]
                )
                status.update(label="Done", state="complete")

            total_time = _time.time() - t_start

            stats_block = (
                f"\n\n---\n"
                f"**Total:** {total_time:.1f}s"
            )
            content_with_stats = content + stats_block

            if st.session_state.gen != gen_at_start:
                st.rerun()
            else:
                st.session_state.messages.append(
                    {"role": "assistant", "content": content_with_stats}
                )
                render_response(content_with_stats)
        except Exception as e:
            if st.session_state.gen != gen_at_start:
                st.rerun()
            else:
                st.error(f"Error: {e}")
