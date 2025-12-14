import io
import json
import time
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm


# ---------------------------
# Excel columns
# ---------------------------
COL_QUESTION = "Question"
COL_A = "Option A"
COL_B = "Option B"
COL_C = "Option C"
COL_D = "Option D"
COL_CORRECT = "Correct Answer"   # A/B/C/D

COL_EXPL = "Explanation"         # optional
COL_SECTION = "Section"          # optional

REQUIRED_COLS = [COL_QUESTION, COL_A, COL_B, COL_C, COL_D, COL_CORRECT]
OPTIONAL_COLS = [COL_EXPL, COL_SECTION]


# ---------------------------
# Data model
# ---------------------------
@dataclass
class MCQ:
    qid: int
    question: str
    options: Dict[str, str]
    correct: str
    explanation: str
    section: str


# ---------------------------
# Utilities
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

        mcqs.append(MCQ(qid=qid, question=q, options=opts, correct=corr,
                        explanation=expl, section=sec))
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


def compute_remaining_seconds() -> int:
    """
    No background reruns. Remaining time is computed from timestamps whenever
    the page rerenders due to user interaction.
    """
    total = int(st.session_state.total_seconds)
    if not st.session_state.running:
        return int(st.session_state.remaining_seconds)

    start_ts = st.session_state.test_start_ts
    paused_total = st.session_state.paused_total_sec

    # If currently paused, include the ongoing pause duration too
    if st.session_state.paused and st.session_state.pause_start_ts is not None:
        paused_total = paused_total + (time.time() - st.session_state.pause_start_ts)

    elapsed_active = max(0.0, time.time() - start_ts - paused_total)
    remaining = int(max(0, total - elapsed_active))
    return remaining


def timer_color(remaining: int) -> str:
    # Visual warning states
    if remaining <= 5 * 60:
        return "danger"
    if remaining <= 10 * 60:
        return "warning"
    return "ok"


def make_pdf(summary: dict, df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    def draw_wrapped(text: str, x: float, y: float, max_w: float, line_h: float) -> float:
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
                    c.setFont("Helvetica", 10)
        if line:
            c.drawString(x, y, line)
            y -= line_h
        return y

    y = h - 2 * cm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, y, "UPSC Practice Test Report")
    y -= 1.0 * cm

    c.setFont("Helvetica", 11)
    for ln in [
        f"Score: {summary['score']}/{summary['total']}",
        f"Correct: {summary['correct']}   Wrong: {summary['wrong']}   Unanswered: {summary['unanswered']}",
        f"Accuracy: {summary['accuracy']}%   Time: {summary['time_taken']}",
        f"Negative mark per wrong: -{summary['negative_mark']}",
    ]:
        c.drawString(2 * cm, y, ln)
        y -= 0.7 * cm

    y -= 0.2 * cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2 * cm, y, "Review (first 60 items shown)")
    y -= 0.8 * cm

    c.setFont("Helvetica", 10)
    max_rows = min(60, len(df))
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


def compute_report(mcqs: List[MCQ], negative_mark: float) -> Tuple[dict, pd.DataFrame]:
    total_seconds = int(st.session_state.total_seconds)
    remaining_seconds = int(st.session_state.remaining_seconds)

    total = len(mcqs)
    correct = wrong = unanswered = 0
    score = 0.0

    rows = []
    for m in mcqs:
        your = st.session_state.answers.get(m.qid)
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
            "Visited": ("Yes" if m.qid in st.session_state.visited else "No"),
            "Flagged": ("Yes" if m.qid in st.session_state.flagged else "No"),
            "Difficulty": st.session_state.difficulty.get(m.qid, ""),
            "Your": your or "",
            "Correct": m.correct,
            "Result": res,
            "Time(s)": round(float(st.session_state.time_spent.get(m.qid, 0.0)), 1),
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
        "dark_mode": st.session_state.dark_mode,
        "randomize": st.session_state.pref_randomize,
        "qcount": st.session_state.pref_qcount,
        "selected_sections": st.session_state.pref_sections,
        "flagged": list(st.session_state.flagged),
        "visited": list(st.session_state.visited),
        "difficulty": st.session_state.difficulty,
        "test_start_ts": st.session_state.test_start_ts,
        "paused_total_sec": st.session_state.paused_total_sec,
        "pause_start_ts": st.session_state.pause_start_ts,
        "q_enter_ts": st.session_state.q_enter_ts,
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
            explanation=str(d.get("explanation", "")),
            section=str(d.get("section", "General")),
        ))

    st.session_state.mcqs = mcqs
    st.session_state.answers = {int(k): (v if v in ("A", "B", "C", "D") else None) for k, v in data.get("answers", {}).items()}
    st.session_state.time_spent = {int(k): float(v) for k, v in data.get("time_spent", {}).items()}
    st.session_state.current = int(data.get("current", 0))

    st.session_state.running = bool(data.get("running", False))
    st.session_state.paused = bool(data.get("paused", False))

    st.session_state.total_seconds = int(data.get("total_seconds", 20 * 60))
    st.session_state.remaining_seconds = int(data.get("remaining_seconds", st.session_state.total_seconds))

    st.session_state.negative_mark = float(data.get("negative_mark", 1/3))
    st.session_state.dark_mode = bool(data.get("dark_mode", False))

    st.session_state.pref_randomize = bool(data.get("randomize", True))
    st.session_state.pref_qcount = int(data.get("qcount", 20))
    st.session_state.pref_sections = list(data.get("selected_sections", ["All"]))

    st.session_state.flagged = set(int(x) for x in data.get("flagged", []))
    st.session_state.visited = set(int(x) for x in data.get("visited", []))
    st.session_state.difficulty = {int(k): str(v) for k, v in data.get("difficulty", {}).items()}

    st.session_state.test_start_ts = float(data.get("test_start_ts", time.time()))
    st.session_state.paused_total_sec = float(data.get("paused_total_sec", 0.0))
    st.session_state.pause_start_ts = data.get("pause_start_ts", None)
    if st.session_state.pause_start_ts is not None:
        st.session_state.pause_start_ts = float(st.session_state.pause_start_ts)

    st.session_state.q_enter_ts = data.get("q_enter_ts", None)
    if st.session_state.q_enter_ts is not None:
        st.session_state.q_enter_ts = float(st.session_state.q_enter_ts)

    st.session_state.show_report = False


# ---------------------------
# CSS (Sticky header + clean touch UI)
# ---------------------------
def apply_css(dark: bool):
    if dark:
        bg = "#0b1220"
        card = "#0f172a"
        text = "#e5e7eb"
        muted = "#94a3b8"
        border = "rgba(148,163,184,0.22)"
        danger = "#ef4444"
        warning = "#f59e0b"
        ok = "#10b981"
    else:
        bg = "#f7f9fc"
        card = "#ffffff"
        text = "#0f172a"
        muted = "rgba(60,60,60,0.75)"
        border = "rgba(15,23,42,0.12)"
        danger = "#dc2626"
        warning = "#d97706"
        ok = "#059669"

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
      .sticky {{
        position: sticky;
        top: 0;
        z-index: 999;
        padding-top: 6px;
        padding-bottom: 8px;
        background: {bg};
      }}
      .timer-ok {{ color: {ok}; font-weight: 900; }}
      .timer-warning {{ color: {warning}; font-weight: 900; }}
      .timer-danger {{ color: {danger}; font-weight: 900; }}
      div.stButton > button {{
        padding: 14px 16px !important;
        border-radius: 16px !important;
        font-weight: 900 !important;
        width: 100% !important;
        white-space: normal !important;
        line-height: 1.2 !important;
      }}
      section.main > div {{
        padding-top: 1.0rem;
      }}
    </style>
    """, unsafe_allow_html=True)


# ---------------------------
# State init
# ---------------------------
def init_state():
    st.session_state.setdefault("pool", None)

    st.session_state.setdefault("mcqs", [])
    st.session_state.setdefault("answers", {})
    st.session_state.setdefault("time_spent", {})
    st.session_state.setdefault("current", 0)

    st.session_state.setdefault("visited", set())
    st.session_state.setdefault("flagged", set())
    st.session_state.setdefault("difficulty", {})  # qid -> Easy/Medium/Hard

    st.session_state.setdefault("running", False)
    st.session_state.setdefault("paused", False)
    st.session_state.setdefault("show_report", False)

    st.session_state.setdefault("total_seconds", 20 * 60)
    st.session_state.setdefault("remaining_seconds", 20 * 60)

    # Timer timestamps (no reruns)
    st.session_state.setdefault("test_start_ts", time.time())
    st.session_state.setdefault("paused_total_sec", 0.0)
    st.session_state.setdefault("pause_start_ts", None)

    # Question time tracking
    st.session_state.setdefault("q_enter_ts", None)

    # Preferences
    st.session_state.setdefault("dark_mode", False)
    st.session_state.setdefault("autosave_enabled", True)

    st.session_state.setdefault("negative_mark", 1/3)
    st.session_state.setdefault("pref_qcount", 20)
    st.session_state.setdefault("pref_randomize", True)
    st.session_state.setdefault("pref_sections", ["All"])


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
    st.session_state.show_report = False

    st.session_state.test_start_ts = time.time()
    st.session_state.paused_total_sec = 0.0
    st.session_state.pause_start_ts = None

    st.session_state.remaining_seconds = int(st.session_state.total_seconds)
    st.session_state.q_enter_ts = time.time()


def pause_test():
    if not st.session_state.running or st.session_state.paused:
        return
    commit_time_for_current()
    st.session_state.paused = True
    st.session_state.pause_start_ts = time.time()


def resume_test():
    if not st.session_state.running or not st.session_state.paused:
        return
    # add paused duration
    if st.session_state.pause_start_ts is not None:
        st.session_state.paused_total_sec += max(0.0, time.time() - st.session_state.pause_start_ts)
    st.session_state.pause_start_ts = None
    st.session_state.paused = False
    st.session_state.q_enter_ts = time.time()


def stop_test():
    if st.session_state.running and not st.session_state.paused:
        commit_time_for_current()
    st.session_state.running = False
    st.session_state.paused = False
    st.session_state.pause_start_ts = None
    st.session_state.q_enter_ts = None
    st.session_state.show_report = True


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


def palette_state(qid: int) -> str:
    """
    Unvisited, Visited-unanswered, Answered, Flagged (flag overrides).
    """
    if qid in st.session_state.flagged:
        return "⭐"
    ans = st.session_state.answers.get(qid)
    if qid not in st.session_state.visited:
        return "⬜"  # unvisited
    if ans is None:
        return "🟦"  # visited but unanswered
    return "✅"      # answered


def autosave_snapshot_bytes() -> Optional[bytes]:
    if not st.session_state.autosave_enabled:
        return None
    return export_progress_json()


# ---------------------------
# UI helpers
# ---------------------------
def option_button(letter: str, text: str, selected: bool, disabled: bool, key: str) -> bool:
    label = f"{letter}. {text}"
    if selected:
        label = f"✅ {label}"
    return st.button(label, key=key, disabled=disabled, use_container_width=True)


# ---------------------------
# App
# ---------------------------
def main():
    st.set_page_config(page_title="UPSC Touch Test (Cloud)", layout="wide")
    init_state()
    apply_css(st.session_state.dark_mode)

    st.title("UPSC Touch Test (Excel Only)")
    st.markdown('<div class="muted">Touch-first, iPad-ready. No OpenAI. Fast timer (no rerun loop).</div>', unsafe_allow_html=True)

    # Compute remaining and store (so report is consistent)
    st.session_state.remaining_seconds = compute_remaining_seconds()
    if st.session_state.running and st.session_state.remaining_seconds <= 0:
        stop_test()

    # ---------------- Sidebar ----------------
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
            st.write("If 'Section' exists, you can run section-wise tests.")

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

        # Preferences (persist for session)
        st.session_state.pref_sections = st.multiselect(
            "Section-wise test",
            options=section_choices,
            default=st.session_state.pref_sections if st.session_state.pref_sections else ["All"]
        )
        st.session_state.pref_qcount = st.number_input("Questions (1–100)", min_value=1, max_value=100,
                                                       value=int(st.session_state.pref_qcount), step=1)
        st.session_state.pref_randomize = st.checkbox("Randomize selection", value=bool(st.session_state.pref_randomize))
        minutes = st.number_input("Timer (minutes)", min_value=1, max_value=300,
                                  value=max(1, int(st.session_state.total_seconds // 60)), step=1)

        st.session_state.negative_mark = st.slider(
            "UPSC negative marking (per wrong)",
            min_value=0.0, max_value=1.0,
            value=float(st.session_state.negative_mark),
            step=0.05
        )

        st.divider()

        # Build test set
        if st.button("Load / Apply Question Set", type="primary", use_container_width=True,
                     disabled=(st.session_state.pool is None) or st.session_state.running):
            filt = filter_by_section(st.session_state.pool, st.session_state.pref_sections)
            if not filt:
                st.error("No questions found for selected section(s).")
            else:
                chosen = pick_questions(filt, st.session_state.pref_qcount, st.session_state.pref_randomize)
                st.session_state.mcqs = chosen
                st.session_state.answers = {m.qid: None for m in chosen}
                st.session_state.time_spent = {m.qid: 0.0 for m in chosen}
                st.session_state.current = 0
                st.session_state.visited = set()
                st.session_state.flagged = set()
                st.session_state.difficulty = {}
                st.session_state.running = False
                st.session_state.paused = False
                st.session_state.total_seconds = int(minutes) * 60
                st.session_state.remaining_seconds = int(st.session_state.total_seconds)
                st.session_state.show_report = False
                st.success("Ready. Press Start.")

        # Controls
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Start", use_container_width=True,
                         disabled=(not st.session_state.mcqs) or st.session_state.running):
                start_test()
        with c2:
            if st.button("Stop & Report", use_container_width=True, disabled=(not st.session_state.mcqs)):
                stop_test()

        c3, c4 = st.columns(2)
        with c3:
            if st.button("Pause", use_container_width=True,
                         disabled=(not st.session_state.running) or st.session_state.paused):
                pause_test()
        with c4:
            if st.button("Resume", use_container_width=True,
                         disabled=(not st.session_state.running) or (not st.session_state.paused)):
                resume_test()

        st.divider()

        # Manual refresh (for timer if you want)
        st.button("Refresh timer", use_container_width=True)

        # Autosave/restore
        snap = autosave_snapshot_bytes()
        if snap:
            st.download_button(
                "Download autosave (JSON)",
                data=snap,
                file_name="upsc_autosave.json",
                mime="application/json",
                use_container_width=True
            )

        restore_file = st.file_uploader("Restore progress (JSON)", type=["json"], key="restore_json")
        if restore_file is not None:
            try:
                import_progress_json(restore_file.read())
                st.success("Progress restored.")
            except Exception as e:
                st.error(f"Restore failed: {e}")

    # ---------------- Main area ----------------
    mcqs: List[MCQ] = st.session_state.mcqs
    if not mcqs:
        st.info("Upload Excel → choose settings → click **Load / Apply Question Set** (sidebar).")
        return

    # Sticky header
    remaining = int(st.session_state.remaining_seconds)
    state = timer_color(remaining)
    timer_class = "timer-ok" if state == "ok" else ("timer-warning" if state == "warning" else "timer-danger")

    unanswered = sum(1 for m in mcqs if st.session_state.answers.get(m.qid) is None)
    flagged = len(st.session_state.flagged)

    st.markdown('<div class="sticky">', unsafe_allow_html=True)
    st.markdown('<div class="card">', unsafe_allow_html=True)
    h1, h2, h3, h4, h5 = st.columns([1.25, 1.1, 1.2, 1.0, 1.2])

    with h1:
        st.markdown(f"<div class='{timer_class}'>Time left: {fmt_hhmmss(remaining)}</div>", unsafe_allow_html=True)
    with h2:
        st.markdown(f"<b>Status:</b> {'Running' if st.session_state.running else 'Stopped'}"
                    f"{' (Paused)' if st.session_state.paused else ''}", unsafe_allow_html=True)
    with h3:
        st.markdown(f"<b>Question:</b> {st.session_state.current + 1}/{len(mcqs)}", unsafe_allow_html=True)
    with h4:
        st.markdown(f"<b>Unanswered:</b> {unanswered}", unsafe_allow_html=True)
    with h5:
        st.markdown(f"<b>Flagged:</b> {flagged}", unsafe_allow_html=True)

    st.markdown("</div></div>", unsafe_allow_html=True)

    # Layout: Question/Options + Palette
    left, right = st.columns([2.4, 1.0], gap="large")

    idx = st.session_state.current
    m = mcqs[idx]

    # Mark visited
    st.session_state.visited.add(m.qid)

    running = st.session_state.running and (not st.session_state.paused)

    with left:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader(f"Q{idx+1}. {m.section}")
        st.write(m.question)

        # Flag + Difficulty row
        f1, f2, f3 = st.columns([1.2, 1.6, 1.2])
        with f1:
            flagged_now = (m.qid in st.session_state.flagged)
            if st.button("⭐ Unflag" if flagged_now else "⭐ Flag", use_container_width=True):
                if flagged_now:
                    st.session_state.flagged.remove(m.qid)
                else:
                    st.session_state.flagged.add(m.qid)
        with f2:
            # Difficulty tag (always available; useful post-answer too)
            current_diff = st.session_state.difficulty.get(m.qid, "—")
            diff = st.selectbox(
                "Difficulty",
                options=["—", "Easy", "Medium", "Hard"],
                index=["—", "Easy", "Medium", "Hard"].index(current_diff) if current_diff in ["—", "Easy", "Medium", "Hard"] else 0,
                key=f"diff_{m.qid}"
            )
            if diff != "—":
                st.session_state.difficulty[m.qid] = diff
            elif m.qid in st.session_state.difficulty:
                del st.session_state.difficulty[m.qid]
        with f3:
            # Quick jump helpers
            if st.button("First unanswered", use_container_width=True):
                for j, q in enumerate(mcqs):
                    if st.session_state.answers.get(q.qid) is None:
                        goto(j)
                        break

        # Options 2x2 (always visible on iPad)
        selected = st.session_state.answers.get(m.qid)

        r1c1, r1c2 = st.columns(2, gap="medium")
        with r1c1:
            if option_button("A", m.options["A"], selected == "A", disabled=not running, key=f"optA_{m.qid}"):
                st.session_state.answers[m.qid] = "A"
        with r1c2:
            if option_button("B", m.options["B"], selected == "B", disabled=not running, key=f"optB_{m.qid}"):
                st.session_state.answers[m.qid] = "B"

        r2c1, r2c2 = st.columns(2, gap="medium")
        with r2c1:
            if option_button("C", m.options["C"], selected == "C", disabled=not running, key=f"optC_{m.qid}"):
                st.session_state.answers[m.qid] = "C"
        with r2c2:
            if option_button("D", m.options["D"], selected == "D", disabled=not running, key=f"optD_{m.qid}"):
                st.session_state.answers[m.qid] = "D"

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
        with nav4:
            if st.button("Go to flagged", use_container_width=True):
                # jump to first flagged
                flagged_list = sorted(st.session_state.flagged)
                if flagged_list:
                    target_qid = flagged_list[0]
                    for j, q in enumerate(mcqs):
                        if q.qid == target_qid:
                            goto(j)
                            break

        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Palette")

        # Legend
        st.markdown(
            "<div class='muted'>⬜ unvisited &nbsp; 🟦 visited-unanswered &nbsp; ✅ answered &nbsp; ⭐ flagged</div>",
            unsafe_allow_html=True
        )

        cols = st.columns(5)
        for i, q in enumerate(mcqs):
            s = palette_state(q.qid)
            label = f"{s} {i+1}"
            col = cols[i % 5]
            if col.button(label, key=f"pal_{i}", use_container_width=True):
                goto(i)

        st.markdown("</div>", unsafe_allow_html=True)

    # ---------------- Report / Analysis ----------------
    if st.session_state.show_report:
        st.divider()
        st.header("Analysis Report")

        summary, df = compute_report(mcqs, float(st.session_state.negative_mark))

        a, b, c, d, e, f = st.columns(6)
        a.metric("Score", f"{summary['score']}/{summary['total']}")
        b.metric("Correct", summary["correct"])
        c.metric("Wrong", summary["wrong"])
        d.metric("Unanswered", summary["unanswered"])
        e.metric("Accuracy", f"{summary['accuracy']}%")
        f.metric("Time", summary["time_taken"])

        st.subheader("Filters")
        flt1, flt2, flt3, flt4 = st.columns([1.2, 1.2, 1.2, 1.8])
        with flt1:
            show_only = st.selectbox(
                "Show",
                ["All", "Wrong", "Unanswered", "Correct", "Flagged", "Hard", "Hard + Wrong"],
                index=0
            )
        with flt2:
            sec_opts = ["All"] + sorted(df["Section"].unique().tolist())
            sec_pick = st.selectbox("Section", sec_opts, index=0)
        with flt3:
            visited_pick = st.selectbox("Visited", ["All", "Yes", "No"], index=0)
        with flt4:
            search = st.text_input("Search text (question/explanation)", value="")

        view = df.copy()

        if show_only == "Wrong":
            view = view[view["Result"] == "Wrong"]
        elif show_only == "Unanswered":
            view = view[view["Result"] == "Unanswered"]
        elif show_only == "Correct":
            view = view[view["Result"] == "Correct"]
        elif show_only == "Flagged":
            view = view[view["Flagged"] == "Yes"]
        elif show_only == "Hard":
            view = view[view["Difficulty"] == "Hard"]
        elif show_only == "Hard + Wrong":
            view = view[(view["Difficulty"] == "Hard") & (view["Result"] == "Wrong")]

        if sec_pick != "All":
            view = view[view["Section"] == sec_pick]

        if visited_pick != "All":
            view = view[view["Visited"] == visited_pick]

        if search.strip():
            s = search.strip().lower()
            view = view[
                view["Question"].str.lower().str.contains(s, na=False)
                | view["Explanation"].str.lower().str.contains(s, na=False)
            ]

        st.subheader("Review Table")
        st.dataframe(view, use_container_width=True, height=420)

        st.subheader("Explanations (tap to expand)")
        for _, r in view.iterrows():
            title = f"Q{int(r['#'])} — Your: {r['Your'] or '—'} | Correct: {r['Correct']} | {r['Result']} | {r.get('Section','')}"
            with st.expander(title, expanded=False):
                st.write(r["Question"])
                st.markdown("**Explanation:**")
                st.write(r["Explanation"] if r["Explanation"] else "No explanation in Excel.")

        st.download_button(
            "Download report as CSV",
            data=view.to_csv(index=False).encode("utf-8"),
            file_name="upsc_test_report_filtered.csv",
            mime="text/csv",
            use_container_width=True
        )

        pdf_bytes = make_pdf(summary, df)
        st.download_button(
            "Download full report as PDF",
            data=pdf_bytes,
            file_name="upsc_test_report.pdf",
            mime="application/pdf",
            use_container_width=True
        )


if __name__ == "__main__":
    main()
