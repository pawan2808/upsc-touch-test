import time
import random
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

# ---------------------------
# Excel schema
# ---------------------------
COL_QUESTION = "Question"
COL_A = "Option A"
COL_B = "Option B"
COL_C = "Option C"
COL_D = "Option D"
COL_CORRECT = "Correct Answer"   # A/B/C/D
COL_EXPL = "Explanation"

REQUIRED_COLS = [COL_QUESTION, COL_A, COL_B, COL_C, COL_D, COL_CORRECT, COL_EXPL]


# ---------------------------
# Data model
# ---------------------------
@dataclass
class MCQ:
    qid: int
    question: str
    options: Dict[str, str]   # A/B/C/D -> text
    correct: str              # A/B/C/D
    explanation: str          # text


# ---------------------------
# Helpers
# ---------------------------
def load_excel_mcqs(uploaded_file) -> List[MCQ]:
    df = pd.read_excel(uploaded_file, engine="openpyxl")

    # allow missing Explanation column (auto-add)
    for col in REQUIRED_COLS:
        if col not in df.columns:
            if col == COL_EXPL:
                df[COL_EXPL] = ""
            else:
                raise ValueError(f"Missing required column: {col}")

    mcqs: List[MCQ] = []
    qid = 1
    for _, r in df.iterrows():
        q = str(r[COL_QUESTION]).strip()
        if not q or q.lower() == "nan":
            continue

        opts = {
            "A": str(r[COL_A]).strip(),
            "B": str(r[COL_B]).strip(),
            "C": str(r[COL_C]).strip(),
            "D": str(r[COL_D]).strip(),
        }
        corr = str(r[COL_CORRECT]).strip().upper()
        if corr not in ("A", "B", "C", "D"):
            corr = "A"

        expl = str(r.get(COL_EXPL, "")).strip()
        if expl.lower() == "nan":
            expl = ""

        mcqs.append(MCQ(qid=qid, question=q, options=opts, correct=corr, explanation=expl))
        qid += 1

    if not mcqs:
        raise ValueError("No valid questions found in the Excel.")
    return mcqs


def pick_questions(pool: List[MCQ], n: int, randomize: bool) -> List[MCQ]:
    n = max(1, min(100, int(n)))
    n = min(n, len(pool))
    items = list(pool)
    if randomize:
        random.shuffle(items)
    chosen = items[:n]
    # re-number qids 1..n
    for i, m in enumerate(chosen, start=1):
        m.qid = i
    return chosen


def fmt_hhmmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def compute_report(mcqs: List[MCQ], answers: Dict[int, Optional[str]], time_spent: Dict[int, float],
                   total_seconds: int, remaining_seconds: int, negative_ratio: float = 1/3):
    total = len(mcqs)
    correct = wrong = unanswered = 0
    score = 0.0

    rows = []
    for m in mcqs:
        your = answers.get(m.qid)
        if your is None:
            unanswered += 1
            res = "Unanswered"
            marks = 0.0
        elif your == m.correct:
            correct += 1
            res = "Correct"
            marks = 1.0
        else:
            wrong += 1
            res = "Wrong"
            marks = -negative_ratio

        score += marks
        rows.append({
            "#": m.qid,
            "Your": your or "",
            "Correct": m.correct,
            "Result": res,
            "Time(s)": round(float(time_spent.get(m.qid, 0.0)), 1),
            "Marks": round(float(marks), 2),
            "Question": m.question,
            "Explanation": m.explanation or "",
        })

    attempted = total - unanswered
    accuracy = (correct / attempted * 100.0) if attempted > 0 else 0.0
    time_taken = total_seconds - remaining_seconds

    summary = {
        "score": round(score, 2),
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "unanswered": unanswered,
        "accuracy": round(accuracy, 1),
        "time_taken": fmt_hhmmss(int(time_taken)),
    }
    return summary, rows


# ---------------------------
# Touch-first CSS
# ---------------------------
TOUCH_CSS = """
<style>
/* Make app look like a touch app */
html, body, [class*="css"]  {
  font-size: 18px !important;
}
button[kind="primary"], button[kind="secondary"] {
  padding: 14px 18px !important;
  border-radius: 14px !important;
  font-weight: 800 !important;
}
div.stRadio > div {
  gap: 12px !important;
}
div.stRadio label {
  border: 2px solid rgba(120,120,120,0.35);
  border-radius: 16px;
  padding: 14px 14px;
  margin: 6px 0px;
}
div.stRadio label:hover {
  background: rgba(34,197,94,0.18);
}
.small-muted {
  color: rgba(120,120,120,0.9);
  font-size: 0.95rem;
}
.card {
  border: 2px solid rgba(120,120,120,0.25);
  border-radius: 18px;
  padding: 14px 14px;
}
.timer {
  font-size: 1.35rem;
  font-weight: 900;
}
</style>
"""


# ---------------------------
# Session state init
# ---------------------------
def init_state():
    st.session_state.setdefault("pool", None)             # full excel pool: List[MCQ]
    st.session_state.setdefault("mcqs", [])               # active test set
    st.session_state.setdefault("answers", {})            # qid -> A/B/C/D/None
    st.session_state.setdefault("time_spent", {})         # qid -> seconds
    st.session_state.setdefault("current", 0)             # index in active list
    st.session_state.setdefault("running", False)
    st.session_state.setdefault("paused", False)
    st.session_state.setdefault("total_seconds", 20 * 60)
    st.session_state.setdefault("remaining_seconds", 20 * 60)
    st.session_state.setdefault("last_tick", None)
    st.session_state.setdefault("q_enter_ts", None)
    st.session_state.setdefault("show_report", False)


def start_test():
    st.session_state.running = True
    st.session_state.paused = False
    st.session_state.last_tick = time.time()
    st.session_state.q_enter_ts = time.time()
    st.session_state.show_report = False


def pause_test():
    if not st.session_state.running or st.session_state.paused:
        return
    commit_time_for_current()
    st.session_state.paused = True
    st.session_state.last_tick = None


def resume_test():
    if not st.session_state.running or not st.session_state.paused:
        return
    st.session_state.paused = False
    st.session_state.last_tick = time.time()
    st.session_state.q_enter_ts = time.time()


def stop_test():
    if st.session_state.running and not st.session_state.paused:
        commit_time_for_current()
    st.session_state.running = False
    st.session_state.paused = False
    st.session_state.last_tick = None
    st.session_state.q_enter_ts = None
    st.session_state.show_report = True


def commit_time_for_current():
    mcqs = st.session_state.mcqs
    if not mcqs:
        return
    idx = st.session_state.current
    idx = max(0, min(idx, len(mcqs) - 1))
    qid = mcqs[idx].qid
    enter = st.session_state.q_enter_ts
    if enter is None:
        return
    st.session_state.time_spent[qid] = st.session_state.time_spent.get(qid, 0.0) + max(0.0, time.time() - enter)
    st.session_state.q_enter_ts = None


def tick_timer():
    if not st.session_state.running or st.session_state.paused:
        return
    now = time.time()
    last = st.session_state.last_tick
    if last is None:
        st.session_state.last_tick = now
        return
    dt = now - last
    st.session_state.last_tick = now

    st.session_state.remaining_seconds = max(0, int(st.session_state.remaining_seconds - dt))

    if st.session_state.remaining_seconds <= 0:
        stop_test()


def goto(idx: int):
    mcqs = st.session_state.mcqs
    if not mcqs:
        return
    idx = max(0, min(idx, len(mcqs) - 1))
    if idx == st.session_state.current:
        return
    if st.session_state.running and not st.session_state.paused:
        commit_time_for_current()
        st.session_state.q_enter_ts = time.time()
    st.session_state.current = idx


# ---------------------------
# Streamlit App
# ---------------------------
def main():
    st.set_page_config(page_title="UPSC Touch Test (Excel Only)", layout="wide")
    st.markdown(TOUCH_CSS, unsafe_allow_html=True)
    init_state()

    tick_timer()  # update timer on each rerun

    st.title("UPSC Touch Test (Excel Only)")
    st.markdown('<div class="small-muted">iPad/touch-friendly. No ChatGPT/OpenAI features. Excel → Test → Analysis.</div>', unsafe_allow_html=True)

    # Sidebar setup
    with st.sidebar:
        st.header("Setup")
        uploaded = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"])

        with st.expander("Excel format instructions", expanded=False):
            st.write("Your Excel must have these columns:")
            st.code(
                "\n".join(REQUIRED_COLS),
                language="text"
            )
            st.write("Correct Answer must be A/B/C/D. Explanation can be blank.")

        if uploaded is not None:
            try:
                pool = load_excel_mcqs(uploaded)
                st.session_state.pool = pool
                st.success(f"Loaded {len(pool)} questions from Excel.")
            except Exception as e:
                st.session_state.pool = None
                st.error(str(e))

        qcount = st.number_input("Questions (1–100)", min_value=1, max_value=100, value=20, step=1)
        randomize = st.checkbox("Randomize selection", value=False)

        minutes = st.number_input("Timer (minutes)", min_value=1, max_value=300, value=20, step=1)

        st.divider()

        colA, colB, colC = st.columns(3)
        with colA:
            if st.button("Load / Apply", type="primary", use_container_width=True, disabled=st.session_state.pool is None):
                pool = st.session_state.pool
                chosen = pick_questions(pool, qcount, randomize)
                st.session_state.mcqs = chosen
                st.session_state.answers = {m.qid: None for m in chosen}
                st.session_state.time_spent = {m.qid: 0.0 for m in chosen}
                st.session_state.current = 0
                st.session_state.running = False
                st.session_state.paused = False
                st.session_state.total_seconds = int(minutes) * 60
                st.session_state.remaining_seconds = st.session_state.total_seconds
                st.session_state.last_tick = None
                st.session_state.q_enter_ts = None
                st.session_state.show_report = False
                st.toast("Question set ready.", icon="✅")

        with colB:
            if st.button("Start", use_container_width=True, disabled=not st.session_state.mcqs or st.session_state.running):
                start_test()

        with colC:
            if st.button("Stop & Report", use_container_width=True, disabled=not st.session_state.mcqs):
                stop_test()

        colD, colE = st.columns(2)
        with colD:
            if st.button("Pause", use_container_width=True, disabled=not st.session_state.running or st.session_state.paused):
                pause_test()
        with colE:
            if st.button("Resume", use_container_width=True, disabled=not st.session_state.running or not st.session_state.paused):
                resume_test()

    mcqs = st.session_state.mcqs

    if not mcqs:
        st.info("Upload an Excel in the sidebar, then click **Load / Apply**.")
        return

    # Main layout
    left, right = st.columns([2.4, 1])

    # Left: question card
    with left:
        st.markdown('<div class="card">', unsafe_allow_html=True)

        timer_str = fmt_hhmmss(st.session_state.remaining_seconds)
        st.markdown(f'<div class="timer">Time left: {timer_str}</div>', unsafe_allow_html=True)

        idx = st.session_state.current
        m = mcqs[idx]

        st.subheader(f"Q{idx + 1} of {len(mcqs)}")
        st.write(m.question)

        # Touch-friendly radio; store choice
        key = f"ans_{m.qid}"
        current_val = st.session_state.answers.get(m.qid)

        # Streamlit radio expects the exact option label in list.
        # We'll map A/B/C/D to full label but store only A/B/C/D.
        labels = [
            ("A", f"A. {m.options['A']}"),
            ("B", f"B. {m.options['B']}"),
            ("C", f"C. {m.options['C']}"),
            ("D", f"D. {m.options['D']}"),
        ]
        display_list = [lab for _, lab in labels]
        letter_to_display = {k: v for k, v in labels}
        display_to_letter = {v: k for k, v in labels}

        # Determine default index
        default_index = None
        if current_val in letter_to_display:
            default_index = display_list.index(letter_to_display[current_val])

        selected_display = st.radio(
            "Select an option",
            options=display_list,
            index=default_index if default_index is not None else 0,
            key=key,
            label_visibility="collapsed",
            disabled=not st.session_state.running and not st.session_state.show_report
        )

        # Save answer only when test is active (running or paused allowed)
        if st.session_state.running:
            st.session_state.answers[m.qid] = display_to_letter.get(selected_display)

        # Buttons row (big)
        b1, b2, b3, b4 = st.columns(4)
        with b1:
            if st.button("Previous", use_container_width=True):
                goto(idx - 1)
        with b2:
            if st.button("Next", use_container_width=True):
                goto(idx + 1)
        with b3:
            if st.button("Clear", use_container_width=True):
                st.session_state.answers[m.qid] = None
                st.toast("Cleared answer.", icon="🧽")
        with b4:
            if st.button("Jump to first unanswered", use_container_width=True):
                for j, q in enumerate(mcqs):
                    if st.session_state.answers.get(q.qid) is None:
                        goto(j)
                        break

        st.markdown("</div>", unsafe_allow_html=True)

    # Right: palette
    with right:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Palette")

        # Create a grid of buttons (touch)
        cols = st.columns(5)
        for i, q in enumerate(mcqs):
            answered = st.session_state.answers.get(q.qid) is not None
            label = f"{i+1}"
            col = cols[i % 5]
            # Style: answered green badge-like using emoji
            txt = f"✅ {label}" if answered else f"⬜ {label}"
            if col.button(txt, use_container_width=True):
                goto(i)

        st.markdown('<div class="small-muted">✅ answered, ⬜ unanswered</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # Report area
    if st.session_state.show_report:
        st.divider()
        st.header("Analysis Report")

        summary, rows = compute_report(
            mcqs=mcqs,
            answers=st.session_state.answers,
            time_spent=st.session_state.time_spent,
            total_seconds=st.session_state.total_seconds,
            remaining_seconds=st.session_state.remaining_seconds,
        )

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Score", f"{summary['score']}/{summary['total']}")
        c2.metric("Correct", summary["correct"])
        c3.metric("Wrong", summary["wrong"])
        c4.metric("Unanswered", summary["unanswered"])
        c5.metric("Accuracy", f"{summary['accuracy']}%")
        c6.metric("Time", summary["time_taken"])

        df = pd.DataFrame(rows)

        st.subheader("Review Table")
        st.dataframe(df, use_container_width=True, height=380)

        st.subheader("Explanations (tap to expand)")
        for r in rows:
            title = f"Q{r['#']} — Your: {r['Your'] or '—'} | Correct: {r['Correct']} | {r['Result']}"
            with st.expander(title, expanded=False):
                st.write(r["Question"])
                st.markdown("**Explanation:**")
                st.write(r["Explanation"] if r["Explanation"] else "No explanation provided in Excel.")

        st.download_button(
            "Download report as CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="upsc_test_report.csv",
            mime="text/csv",
            use_container_width=True
        )

    # Auto-refresh while running (touch-friendly timer)
    if st.session_state.running and not st.session_state.paused:
        time.sleep(0.25)
        st.rerun()


if __name__ == "__main__":
    main()
