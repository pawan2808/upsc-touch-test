import io
import json
import time
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

# PDF export
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm


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
COL_SECTION = "Section"          # OPTIONAL

REQUIRED_COLS = [COL_QUESTION, COL_A, COL_B, COL_C, COL_D, COL_CORRECT]
OPTIONAL_COLS = [COL_EXPL, COL_SECTION]


# ---------------------------
# Data model
# ---------------------------
@dataclass
class MCQ:
    qid: int
    question: str
    options: Dict[str, str]        # A/B/C/D -> text
    correct: str                   # A/B/C/D
    explanation: str               # text
    section: str                   # optional, default "General"


# ---------------------------
# Helpers
# ---------------------------
def fmt_hhmmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def load_excel_mcqs(uploaded_file) -> List[MCQ]:
    df = pd.read_excel(uploaded_file, engine="openpyxl")

    for col in REQUIRED_COLS:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    # Optional columns
    if COL_EXPL not in df.columns:
        df[COL_EXPL] = ""
    if COL_SECTION not in df.columns:
        df[COL_SECTION] = "General"

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

        sec = str(r.get(COL_SECTION, "General")).strip()
        if not sec or sec.lower() == "nan":
            sec = "General"

        mcqs.append(MCQ(qid=qid, question=q, options=opts, correct=corr, explanation=expl, section=sec))
        qid += 1

    if not mcqs:
        raise ValueError("No valid questions found in the Excel.")
    return mcqs


def filter_by_section(pool: List[MCQ], sections: List[str]) -> List[MCQ]:
    if not sections or "All" in sections:
        return list(pool)
    sset = set(sections)
    return [m for m in pool if m.section in sset]


def pick_questions(pool: List[MCQ], n: int, randomize: bool) -> List[MCQ]:
    n = max(1, min(100, int(n)))
    n = min(n, len(pool))
    items = list(pool)
    if randomize:
        random.shuffle(items)
    chosen = items[:n]
    for i, m in enumerate(chosen, start=1):
        m.qid = i
    return chosen


def compute_report(
    mcqs: List[MCQ],
    answers: Dict[int, Optional[str]],
    time_spent: Dict[int, float],
    total_seconds: int,
    remaining_seconds: int,
    negative_mark: float,
) -> Tuple[dict, pd.DataFrame]:
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
            marks = -float(negative_mark)

        score += marks
        rows.append({
            "#": m.qid,
            "Section": m.section,
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
        "negative_mark": float(negative_mark),
    }
    return summary, pd.DataFrame(rows)


def make_pdf(summary: dict, df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    def draw_wrapped(text: str, x: float, y: float, max_w: float, line_h: float) -> float:
        # simple wrap
        words = (text or "").split()
        line = ""
        while words:
            test = (line + " " + words[0]).strip()
            if c.stringWidth(test, "Helvetica", 10) <= max_w:
                line = test
                words.pop(0)
            else:
                c.drawString(x, y, line)
                y -= line_h
                line = ""
                if y < 2 * cm:
                    c.showPage()
                    y = h - 2 * cm
        if line:
            c.drawString(x, y, line)
            y -= line_h
        return y

    y = h - 2 * cm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, y, "UPSC Practice Test Report")
    y -= 1.0 * cm

    c.setFont("Helvetica", 11)
    lines = [
        f"Score: {summary['score']}/{summary['total']}",
        f"Correct: {summary['correct']}   Wrong: {summary['wrong']}   Unanswered: {summary['unanswered']}",
        f"Accuracy: {summary['accuracy']}%   Time: {summary['time_taken']}",
        f"Negative mark per wrong: -{summary['negative_mark']}",
    ]
    for ln in lines:
        c.drawString(2 * cm, y, ln)
        y -= 0.7 * cm

    y -= 0.2 * cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2 * cm, y, "Review (first 50 rows shown)")
    y -= 0.8 * cm

    c.setFont("Helvetica", 10)
    max_rows = min(50, len(df))
    for i in range(max_rows):
        r = df.iloc[i]
        header = f"Q{int(r['#'])} | Your: {r['Your'] or '-'} | Correct: {r['Correct']} | {r['Result']} | Section: {r.get('Section','')}"
        y = draw_wrapped(header, 2 * cm, y, w - 4 * cm, 12)
        y = draw_wrapped(f"Q: {r['Question']}", 2 * cm, y, w - 4 * cm, 12)
        expl = r.get("Explanation", "")
        if expl:
            y = draw_wrapped(f"Exp: {expl}", 2 * cm, y, w - 4 * cm, 12)
        y -= 0.2 * cm
        if y < 2 * cm:
            c.showPage()
            y = h - 2 * cm
            c.setFont("Helvetica", 10)

    c.save()
    return buf.getvalue()


def state_digest() -> str:
    """A small signature to detect changes and autosave progress."""
    mcqs = st.session_state.get("mcqs", [])
    answers = st.session_state.get("answers", {})
    remaining = st.session_state.get("remaining_seconds", 0)
    cur = st.session_state.get("current", 0)
    payload = {
        "n": len(mcqs),
        "answers": answers,
        "remaining": remaining,
        "current": cur,
    }
    return json.dumps(payload, sort_keys=True)


def export_progress_json() -> bytes:
    payload = {
        "mcqs": [
            {
                "qid": m.qid,
                "question": m.question,
                "options": m.options,
                "correct": m.correct,
                "explanation": m.explanation,
                "section": m.section,
            }
            for m in st.session_state.mcqs
        ],
        "answers": st.session_state.answers,
        "time_spent": st.session_state.time_spent,
        "current": st.session_state.current,
        "running": st.session_state.running,
        "paused": st.session_state.paused,
        "total_seconds": st.session_state.total_seconds,
        "remaining_seconds": st.session_state.remaining_seconds,
        "negative_mark": st.session_state.negative_mark,
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def import_progress_json(file_bytes: bytes):
    data = json.loads(file_bytes.decode("utf-8"))
    mcqs = []
    for d in data["mcqs"]:
        mcqs.append(MCQ(
            qid=int(d["qid"]),
            question=str(d["question"]),
            options=dict(d["options"]),
            correct=str(d["correct"]),
            explanation=str(d.get("explanation","")),
            section=str(d.get("section","General")),
        ))

    st.session_state.mcqs = mcqs
    st.session_state.answers = {int(k): (v if v in ("A","B","C","D") else None) for k, v in data["answers"].items()}
    st.session_state.time_spent = {int(k): float(v) for k, v in data.get("time_spent", {}).items()}
    st.session_state.current = int(data.get("current", 0))
    st.session_state.running = bool(data.get("running", False))
    st.session_state.paused = bool(data.get("paused", False))
    st.session_state.total_seconds = int(data.get("total_seconds", 20*60))
    st.session_state.remaining_seconds = int(data.get("remaining_seconds", st.session_state.total_seconds))
    st.session_state.negative_mark = float(data.get("negative_mark", 1/3))
    st.session_state.last_tick = None
    st.session_state.q_enter_ts = None
    st.session_state.show_report = False


# ---------------------------
# Touch-first CSS (no radio styling; avoids vertical text issue)
# ---------------------------
def apply_css(dark: bool):
    if dark:
        bg = "#0b1220"
        card = "#0f172a"
        text = "#e5e7eb"
        muted = "#94a3b8"
        border = "rgba(148,163,184,0.25)"
        btn = "#2563eb"
        btn2 = "#10b981"
    else:
        bg = "#f7f9fc"
        card = "#ffffff"
        text = "#0f172a"
        muted = "rgba(60,60,60,0.75)"
        border = "rgba(15,23,42,0.12)"
        btn = "#1d4ed8"
        btn2 = "#059669"

    st.markdown(f"""
    <style>
    .stApp {{
      background: {bg};
      color: {text};
    }}
    .card {{
      border: 2px solid {border};
      border-radius: 18px;
      padding: 14px 14px;
      background: {card};
    }}
    .muted {{
      color: {muted};
      font-size: 0.95rem;
    }}
    .timer {{
      font-size: 1.25rem;
      font-weight: 900;
    }}
    /* Bigger touch buttons */
    div.stButton > button {{
      padding: 14px 16px !important;
      border-radius: 16px !important;
      font-weight: 900 !important;
      width: 100% !important;
      white-space: normal !important;
      line-height: 1.2 !important;
    }}
    /* Make primary buttons look consistent */
    div.stButton > button[kind="primary"] {{
      background: {btn} !important;
      border: 0 !important;
    }}
    /* Reduce top padding */
    section.main > div {{
      padding-top: 1.0rem;
    }}
    </style>
    """, unsafe_allow_html=True)


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

    st.session_state.setdefault("dark_mode", False)
    st.session_state.setdefault("negative_mark", 1/3)

    # Autosave: store last snapshot in session (cloud-safe)
    st.session_state.setdefault("autosave_enabled", True)
    st.session_state.setdefault("autosave_snapshot", None)
    st.session_state.setdefault("autosave_last_digest", "")


def commit_time_for_current():
    mcqs = st.session_state.mcqs
    if not mcqs:
        return
    idx = max(0, min(st.session_state.current, len(mcqs) - 1))
    qid = mcqs[idx].qid
    enter = st.session_state.q_enter_ts
    if enter is None:
        return
    st.session_state.time_spent[qid] = st.session_state.time_spent.get(qid, 0.0) + max(0.0, time.time() - enter)
    st.session_state.q_enter_ts = None


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


def autosave_if_needed():
    if not st.session_state.autosave_enabled:
        return
    d = state_digest()
    if d != st.session_state.autosave_last_digest:
        st.session_state.autosave_snapshot = export_progress_json()
        st.session_state.autosave_last_digest = d


# ---------------------------
# UI blocks
# ---------------------------
def option_button(letter: str, text: str, selected: bool, disabled: bool, key: str) -> bool:
    # Show a small selected indicator
    label = f"{letter}. {text}"
    if selected:
        label = f"✅ {label}"
    return st.button(label, key=key, disabled=disabled, use_container_width=True)


def main():
    st.set_page_config(page_title="UPSC Touch Test (Cloud)", layout="wide")
    init_state()

    # timer tick per rerun
    tick_timer()

    # Theme
    apply_css(st.session_state.dark_mode)

    st.title("UPSC Touch Test (Excel Only)")
    st.markdown('<div class="muted">iPad-friendly layout. No ChatGPT/OpenAI. Excel → Test → Analysis → PDF export.</div>', unsafe_allow_html=True)

    # ---------------- Sidebar: Setup / Controls ----------------
    with st.sidebar:
        st.header("Setup")

        st.session_state.dark_mode = st.toggle("Night/Dark mode", value=st.session_state.dark_mode)
        st.session_state.autosave_enabled = st.toggle("Autosave progress", value=st.session_state.autosave_enabled)

        uploaded = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"])

        with st.expander("Excel format instructions"):
            st.write("Required columns:")
            st.code("\n".join(REQUIRED_COLS), language="text")
            st.write("Optional columns:")
            st.code("\n".join(OPTIONAL_COLS), language="text")
            st.write("If you include a 'Section' column, you can run section-wise tests.")

        if uploaded is not None:
            try:
                pool = load_excel_mcqs(uploaded)
                st.session_state.pool = pool
                st.success(f"Loaded {len(pool)} questions.")
            except Exception as e:
                st.session_state.pool = None
                st.error(str(e))

        pool = st.session_state.pool or []
        sections = sorted({m.section for m in pool}) if pool else []
        section_choices = ["All"] + sections if sections else ["All"]

        selected_sections = st.multiselect("Section-wise test", options=section_choices, default=["All"])

        qcount = st.number_input("Questions (1–100)", min_value=1, max_value=100, value=20, step=1)
        randomize = st.checkbox("Randomize selection", value=True)

        minutes = st.number_input("Timer (minutes)", min_value=1, max_value=300, value=20, step=1)

        st.session_state.negative_mark = st.slider(
            "UPSC negative marking (per wrong)",
            min_value=0.0,
            max_value=1.0,
            value=float(st.session_state.negative_mark),
            step=0.05
        )

        st.divider()

        # Load / Apply
        if st.button("Load / Apply Question Set", type="primary", use_container_width=True, disabled=st.session_state.pool is None):
            filt = filter_by_section(st.session_state.pool, selected_sections)
            if not filt:
                st.error("No questions found for the selected section(s).")
            else:
                chosen = pick_questions(filt, qcount, randomize)
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
                autosave_if_needed()
                st.success("Ready. Press Start.")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Start", use_container_width=True, disabled=(not st.session_state.mcqs) or st.session_state.running):
                start_test()
        with c2:
            if st.button("Stop & Report", use_container_width=True, disabled=not st.session_state.mcqs):
                stop_test()

        c3, c4 = st.columns(2)
        with c3:
            if st.button("Pause", use_container_width=True, disabled=(not st.session_state.running) or st.session_state.paused):
                pause_test()
        with c4:
            if st.button("Resume", use_container_width=True, disabled=(not st.session_state.running) or (not st.session_state.paused)):
                resume_test()

        st.divider()

        # Progress backup (cloud-safe "autosave": snapshot in session; user can download)
        if st.session_state.autosave_snapshot:
            st.download_button(
                "Download autosave (JSON)",
                data=st.session_state.autosave_snapshot,
                file_name="upsc_autosave.json",
                mime="application/json",
                use_container_width=True
            )

        uploaded_save = st.file_uploader("Restore progress (JSON)", type=["json"], key="restore_json")
        if uploaded_save is not None:
            try:
                import_progress_json(uploaded_save.read())
                st.success("Progress restored.")
            except Exception as e:
                st.error(f"Restore failed: {e}")

    # ---------------- Main: Test UI ----------------
    mcqs: List[MCQ] = st.session_state.mcqs
    if not mcqs:
        st.info("Upload Excel → choose options → click **Load / Apply Question Set** (sidebar).")
        return

    # Autosave whenever state changes
    autosave_if_needed()

    # Header bar (compact)
    top = st.container()
    with top:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        colA, colB, colC, colD = st.columns([1.3, 1.2, 1.2, 1.4])
        with colA:
            st.markdown(f"<div class='timer'>Time left: {fmt_hhmmss(st.session_state.remaining_seconds)}</div>", unsafe_allow_html=True)
        with colB:
            st.markdown(f"<div><b>Status:</b> {'Running' if st.session_state.running else 'Stopped'}{' (Paused)' if st.session_state.paused else ''}</div>", unsafe_allow_html=True)
        with colC:
            cur = st.session_state.current + 1
            st.markdown(f"<div><b>Question:</b> {cur}/{len(mcqs)}</div>", unsafe_allow_html=True)
        with colD:
            unanswered = sum(1 for m in mcqs if st.session_state.answers.get(m.qid) is None)
            st.markdown(f"<div><b>Unanswered:</b> {unanswered}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # Two-column layout: Question/Options + Palette
    left, right = st.columns([2.4, 1.0], gap="large")

    idx = st.session_state.current
    m = mcqs[idx]
    running = st.session_state.running

    with left:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader(f"Q{idx+1}. {m.section}")
        st.write(m.question)

        # Options in a 2x2 grid (always visible; no scrolling for option D)
        selected = st.session_state.answers.get(m.qid)

        r1c1, r1c2 = st.columns(2, gap="medium")
        with r1c1:
            if option_button("A", m.options["A"], selected == "A", disabled=not running, key=f"optA_{m.qid}"):
                st.session_state.answers[m.qid] = "A"
                autosave_if_needed()
        with r1c2:
            if option_button("B", m.options["B"], selected == "B", disabled=not running, key=f"optB_{m.qid}"):
                st.session_state.answers[m.qid] = "B"
                autosave_if_needed()

        r2c1, r2c2 = st.columns(2, gap="medium")
        with r2c1:
            if option_button("C", m.options["C"], selected == "C", disabled=not running, key=f"optC_{m.qid}"):
                st.session_state.answers[m.qid] = "C"
                autosave_if_needed()
        with r2c2:
            if option_button("D", m.options["D"], selected == "D", disabled=not running, key=f"optD_{m.qid}"):
                st.session_state.answers[m.qid] = "D"
                autosave_if_needed()

        nav1, nav2, nav3, nav4 = st.columns(4, gap="medium")
        with nav1:
            if st.button("Previous", use_container_width=True):
                goto(idx - 1)
        with nav2:
            if st.button("Next", use_container_width=True):
                goto(idx + 1)
        with nav3:
            if st.button("Clear", use_container_width=True, disabled=not running):
                st.session_state.answers[m.qid] = None
                autosave_if_needed()
        with nav4:
            if st.button("First unanswered", use_container_width=True):
                for j, q in enumerate(mcqs):
                    if st.session_state.answers.get(q.qid) is None:
                        goto(j)
                        break

        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Palette")

        # 5-column touch palette
        cols = st.columns(5)
        for i, q in enumerate(mcqs):
            ans = st.session_state.answers.get(q.qid)
            txt = f"✅ {i+1}" if ans is not None else f"⬜ {i+1}"
            col = cols[i % 5]
            if col.button(txt, key=f"pal_{i}", use_container_width=True):
                goto(i)

        st.markdown("<div class='muted'>✅ answered, ⬜ unanswered</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # ---------------- Report ----------------
    if st.session_state.show_report:
        st.divider()
        st.header("Analysis Report")

        summary, df = compute_report(
            mcqs=mcqs,
            answers=st.session_state.answers,
            time_spent=st.session_state.time_spent,
            total_seconds=st.session_state.total_seconds,
            remaining_seconds=st.session_state.remaining_seconds,
            negative_mark=float(st.session_state.negative_mark),
        )

        a, b, c, d, e, f = st.columns(6)
        a.metric("Score", f"{summary['score']}/{summary['total']}")
        b.metric("Correct", summary["correct"])
        c.metric("Wrong", summary["wrong"])
        d.metric("Unanswered", summary["unanswered"])
        e.metric("Accuracy", f"{summary['accuracy']}%")
        f.metric("Time", summary["time_taken"])

        st.subheader("Review Table")
        st.dataframe(df, use_container_width=True, height=420)

        st.subheader("Explanations (tap to expand)")
        for _, r in df.iterrows():
            title = f"Q{int(r['#'])} — Your: {r['Your'] or '—'} | Correct: {r['Correct']} | {r['Result']} | {r.get('Section','')}"
            with st.expander(title, expanded=False):
                st.write(r["Question"])
                st.markdown("**Explanation:**")
                st.write(r["Explanation"] if r["Explanation"] else "No explanation in Excel.")

        # Downloads
        st.download_button(
            "Download report as CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="upsc_test_report.csv",
            mime="text/csv",
            use_container_width=True
        )

        pdf_bytes = make_pdf(summary, df)
        st.download_button(
            "Download report as PDF",
            data=pdf_bytes,
            file_name="upsc_test_report.pdf",
            mime="application/pdf",
            use_container_width=True
        )

    # Auto-refresh timer while running (smooth enough, low load)
    if st.session_state.running and not st.session_state.paused:
        time.sleep(2)
        st.rerun()


if __name__ == "__main__":
    main()

