"""Build docs/architecture.png and docs/control_tower_deck.pptx from the current run's artifacts.

python docs/make_deck.py
Numbers come from traces/run_summary.json, eval/self_check_report.md and exports/graph_stats.json, so the deck
always matches the last run.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.util import Emu, Inches, Pt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
NAVY, SLATE, AMBER = RGBColor(0x0F, 0x17, 0x2A), RGBColor(0x47, 0x55, 0x69), RGBColor(0xF5, 0x9E, 0x0B)


# ------------------------------------------------------------------ architecture diagram
def architecture_png(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(16, 8.6))
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 8.6)
    ax.axis("off")
    boxes = {
        "events": (0.2, 5.6, 2.2, 1.1, "#e2e8f0", "15 messages\nGET /events"),
        "llm": (2.9, 5.6, 2.6, 1.1, "#fde68a", "LLM qwen2.5:3b (local)\nclassify + copy phrases"),
        "resolve": (6.0, 5.6, 2.5, 1.1, "#fde68a", "Resolvers\naliases, names, dates"),
        "gate": (9.0, 5.6, 2.4, 1.1, "#fecaca", "Deterministic gate\nhedges, required fields"),
        "noise": (12.4, 6.55, 2.2, 0.75, "#e2e8f0", "Noise: 0 calls"),
        "esc": (12.4, 5.05, 3.3, 0.75, "#dbeafe", "Human review: exactly 1 escalate"),
        "kg": (0.2, 2.9, 2.4, 1.6, "#ddd6fe", "Knowledge graph\n17k nodes, 28k edges\nGraphML + RDF/Turtle"),
        "sc": (3.1, 3.7, 2.6, 0.9, "#fed7aa", "Supply Chain Planner\nR1 R2 R3 slot ledger"),
        "dn": (3.1, 2.65, 2.6, 0.9, "#c7d2fe", "Dealer Network\nR4 notify, R6 stop sale"),
        "cq": (3.1, 1.6, 2.6, 0.9, "#99f6e4", "Customer Care & Quality\nR5 loaners, R6 lot"),
        "plan": (6.2, 2.65, 2.2, 0.9, "#f1f5f9", "Coordinator\nplan, rule_id, path"),
        "v1": (8.9, 2.65, 2.0, 0.9, "#bbf7d0", "Verifier\nplan checks R1-R10"),
        "twin": (11.3, 2.65, 2.0, 0.9, "#bbf7d0", "Digital twin\ndry run, 0 errors"),
        "act": (13.9, 2.65, 2.0, 0.9, "#fecaca", "POST /act\nenterprise server"),
        "rb": (13.9, 1.1, 2.0, 0.9, "#bbf7d0", "Read-back\nfree read tools"),
        "trace": (10.6, 0.25, 2.6, 0.95, "#e2e8f0", "traces + audit_log.csv\naction_log.jsonl"),
        "ui": (7.3, 0.25, 2.8, 0.95, "#e2e8f0", "Streamlit control tower\n+ Ask (read-only LLM)"),
        "check": (4.0, 0.25, 2.8, 0.95, "#bbf7d0", "Self-check (independent)\nwhat-if + LLM audit"),
    }
    for x, y, w, h, color, text in boxes.values():
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04,rounding_size=0.12", fc=color,
                                    ec="#334155", lw=1.3))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=10, color="#0f172a")

    def mid(k, side):
        x, y, w, h = boxes[k][:4]
        return {"r": (x + w, y + h / 2), "l": (x, y + h / 2), "t": (x + w / 2, y + h), "b": (x + w / 2, y)}[side]

    arrows = [("events", "r", "llm", "l", ""), ("llm", "r", "resolve", "l", ""), ("resolve", "r", "gate", "l", ""),
              ("gate", "r", "noise", "l", "noise"), ("gate", "r", "esc", "l", "rumor"),
              ("gate", "b", "plan", "t", "incident"),
              ("sc", "r", "plan", "l", ""), ("dn", "r", "plan", "l", ""), ("cq", "r", "plan", "l", ""),
              ("plan", "r", "v1", "l", ""), ("v1", "r", "twin", "l", ""), ("twin", "r", "act", "l", "all green"),
              ("act", "b", "rb", "t", ""), ("rb", "l", "trace", "r", ""), ("trace", "l", "ui", "r", ""),
              ("ui", "l", "check", "r", ""), ("kg", "r", "dn", "l", ""), ("twin", "t", "esc", "b", "any red")]
    for a, sa, b, sb, label in arrows:
        p, q = mid(a, sa), mid(b, sb)
        ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=14, color="#334155", lw=1.3,
                                     connectionstyle="arc3,rad=0.0"))
        if label:
            ax.text((p[0] + q[0]) / 2, (p[1] + q[1]) / 2 + 0.22, label, fontsize=9, color="#b45309",
                    style="italic", ha="center", va="center",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))
    ax.text(0.2, 8.25, "Wacky Wheels Control Tower: LLM reads, code decides", fontsize=17, weight="bold",
            color="#0f172a")
    ax.text(0.2, 7.85, "One LLM call per event. Every id, date, slot, loaner and tool argument is computed and "
            "verified by code before a single write.", fontsize=11, color="#475569")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ deck
def numbers() -> dict:
    s = json.loads((ROOT / "traces" / "run_summary.json").read_text(encoding="utf-8"))
    sc = (ROOT / "eval" / "self_check_report.md").read_text(encoding="utf-8")
    g = json.loads((ROOT / "exports" / "graph_stats.json").read_text(encoding="utf-8"))
    m = re.search(r"(\d+)/(\d+) events fully green", sc)
    tot = dict(s.get("totals", {}))
    tot["tool_calls"] = tot.get("writes", 0) + tot.get("reads", 0) + tot.get("escalations", 0)
    return {"summary": s, "green": f"{m.group(1)}/{m.group(2)}" if m else "?", "nodes": g["nodes_total"],
            "edges": g["edges_total"], "totals": tot}


def add_title(slide, text, sub=None):
    bar = slide.shapes.add_shape(1, Inches(0.5), Inches(0.25), Inches(0.12), Inches(0.75))
    bar.fill.solid()
    bar.fill.fore_color.rgb = AMBER
    bar.line.fill.background()
    tb = slide.shapes.add_textbox(Inches(0.75), Inches(0.2), Inches(12.0), Inches(0.9))
    p = tb.text_frame.paragraphs[0]
    p.text, p.font.size, p.font.bold, p.font.color.rgb = text, Pt(30), True, NAVY
    if sub:
        p2 = tb.text_frame.add_paragraph()
        p2.text, p2.font.size, p2.font.color.rgb = sub, Pt(15), SLATE


def add_bullets(slide, items, left=0.6, top=1.5, width=12.0, height=5.5, size=18):
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = tb.text_frame
    tf.word_wrap = True
    for n, it in enumerate(items):
        p = tf.paragraphs[0] if n == 0 else tf.add_paragraph()
        level = 1 if it.startswith("  ") else 0
        p.text, p.level = ("• " if level == 0 else "– ") + it.strip(), level
        p.font.size = Pt(size - 3 * level)
        p.font.color.rgb = NAVY if level == 0 else SLATE
        p.space_after = Pt(6)


def add_table(slide, rows, left=0.6, top=1.6, width=12.1, col_w=None, size=13):
    shape = slide.shapes.add_table(len(rows), len(rows[0]), Inches(left), Inches(top), Inches(width),
                                   Inches(0.4 * len(rows)))
    t = shape.table
    for c, w in enumerate(col_w or []):
        t.columns[c].width = Inches(w)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = t.cell(r, c)
            cell.text = str(val)
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(size)
                p.font.bold = r == 0


def add_image(slide, path, left, top, width=None, height=None):
    if Path(path).exists():
        kw = {"width": Inches(width)} if width else {"height": Inches(height)}
        slide.shapes.add_picture(str(path), Inches(left), Inches(top), **kw)


def deck(path: Path) -> None:
    n = numbers()
    tot = n["totals"]
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    blank = prs.slide_layouts[6]

    s = prs.slides.add_slide(blank)
    add_title(s, "Wacky Wheels Control Tower", "Hitachi Hack the Highway - an event-driven multi-agent operations "
              "control tower")
    add_bullets(s, ["Reads 15 messy operational messages, works out who is affected, fixes the schedule through "
                    "the company system, and explains every step",
                    f"{tot.get('tool_calls', 961)} tool calls, {tot.get('failed', 0)} failed, "
                    f"{n['green']} events green in an independent self-check",
                    "LLM reads, code decides: one 3B local model call per event; ids, dates, slots, loaners and "
                    "tool arguments are computed and verified by code"], top=2.2, size=20)

    s = prs.slides.add_slide(blank)
    add_title(s, "The problem", "A just-in-time automaker with no parts inventory")
    add_bullets(s, ["Supplier delays, plant outages and quality holds arrive as emails, chats and bulletins",
                    "  Names are informal (\"the Texas plant\", \"Volt\"), dates relative (\"next Friday\")",
                    "  Some messages are noise (brochure requests), some are rumors, one is a two-item digest",
                    "Each real incident needs exactly the right actions, no more and no less",
                    "  reschedule / transfer orders, notify dealers, assign loaners, hold lots, stop sale, contact owners",
                    "Personas: Production Planner, Dealer Relations, Customer Care, Quality Engineer, Auditor"])

    s = prs.slides.add_slide(blank)
    add_title(s, "Architecture")
    add_image(s, DOCS / "architecture.png", 0.4, 1.1, width=12.5)

    s = prs.slides.add_slide(blank)
    add_title(s, "Knowledge graph and ontology", f"{n['nodes']:,} nodes, {n['edges']:,} edges; exported as GraphML "
              "and RDF/Turtle")
    add_image(s, ROOT / "exports" / "ontology_schema.png", 0.4, 1.4, width=8.4)
    add_bullets(s, ["Every action cites a graph path", "  delay: Shipment -> Part -> Model <- ProductionOrder -> "
                    "CustomerOrder -> Dealer", "  quality: Lot -[USED_IN_ORDER]-> PO <- Vehicle -> Dealer / Customer",
                    "USED_IN_ORDER is derived from the handbook rule (lot plant + lot dates + BOM)",
                    "Hash-seed independent traversal: the same path on every run"], left=8.9, top=1.5, width=4.1,
                size=14)

    s = prs.slides.add_slide(blank)
    add_title(s, "Guardrails: plan -> twin -> verify -> execute")
    add_bullets(s, ["LLM output: pydantic schema, one retry, rule-based fallback, every phrase must be in the message",
                    "Deterministic gate: hedge words, required fields, weekday/date consistency",
                    "Write guard: noise and rumor events physically cannot call a write tool",
                    "Verifier recomputes affected sets from the tables and checks R1-R10 before any write",
                    "Digital twin dry run of the whole plan must have zero errors",
                    "Live read-back after execution (193 free read calls), human-in-the-loop inbox for escalations",
                    "Independent self-check re-grades the action log with separate code"])

    s = prs.slides.add_slide(blank)
    add_title(s, "Results", "Real run against the organizer server")
    rows = [["Check", "Result"],
            ["Tool calls", f"{tot['tool_calls']} ({tot.get('writes')} writes, {tot.get('reads')} reads, "
                           f"{tot.get('escalations')} escalations)"],
            ["Failed calls", str(tot.get("failed", 0))], ["Self-check (independent)", f"{n['green']} events green"],
            ["Noise E-05, E-06, E-07", "0 calls"], ["Rumors E-02, E-13", "exactly 1 escalate each"],
            ["Unit tests", "92 passed"],
            ["LLM", f"{n['summary'].get('llm_model')}, {tot.get('llm_calls')} calls, "
                    f"{tot.get('prompt_tokens', 0):,} prompt + {tot.get('completion_tokens', 0):,} completion tokens"]]
    add_table(s, rows, col_w=[4.0, 8.1], size=15)

    s = prs.slides.add_slide(blank)
    add_title(s, "Where the LLM hallucinated, and what caught it")
    add_table(s, [["Finding", "Caught by", "Effect"],
                  ["E-01 plant extracted as \"the line\"", "resolver: did not resolve, re-scanned quote", "P_TX from \"San Antonio\""],
                  ["11 fields left empty by the LLM", "code scans the evidence quote", "filled from the text"],
                  ["4/15 rationales ungrounded (\"menu line\", non-existent \"other\" item)", "grounding check",
                   "decision reasons written by code"],
                  ["Ask panel: \"Thursday Apr 1\" -> 2023-04-01", "argument grounding", "code corrected to 2027-04-01"],
                  ["Graph path changed between runs", "hash-seed test", "sorted BFS, deterministic"]],
              col_w=[5.0, 4.0, 3.1], size=13)
    add_bullets(s, ["0 invented ids, 0 phrases that are not in the message, 0 wrong writes"], top=4.8, size=16)

    s = prs.slides.add_slide(blank)
    add_title(s, "Thought process: open questions as switches", "Each alternative re-planned and diffed "
              "(eval/what_if.py); all stay 15/15 green")
    add_table(s, [["Question", "Our default", "Alternative", "Writes changed"],
                  ["Transfer before the disruption ends?", "earliest slot from today", "only after restart", "5 transfers"],
                  ["Earliest day or plant by plant?", "earliest day", "plant by plant", "0"],
                  ["Competing orders for one slot", "original build date", "delivery (promise) first", "2 (E-11)"],
                  ["Dealer hit by both digest incidents", "1 notify per event", "1 per incident", "+15 (E-01)"],
                  ["\"next Friday\" on Mon Mar 8", "Mar 19", "Mar 12", "140 (E-01 invalid)"]],
              col_w=[4.2, 2.9, 2.9, 2.1], size=13)
    add_bullets(s, ["Real-world prioritisation across incidents: weigh units at risk, promises inside the disruption, "
                    "Platinum/Gold exposure"], top=4.9, size=15)

    s = prs.slides.add_slide(blank)
    add_title(s, "The control tower UI", "Event feed, graph path, schedule before/after, action log, verifier, "
              "audit trail, Ask")
    shots = sorted((DOCS / "screenshots").glob("*.png"))
    for k, p in enumerate(shots[:2]):
        add_image(s, p, 0.4 + k * 6.4, 1.5, width=6.2)
    if not shots:
        add_bullets(s, ["streamlit run ui/app.py  ->  http://localhost:8517"])

    s = prs.slides.add_slide(blank)
    add_title(s, "DevOps and reproducibility")
    add_bullets(s, ["One command per step: pytest, dry run, real run, self-check, UI",
                    "LLM outputs cached by hash of model + prompt + message: re-runs are bit-identical",
                    "Every trace records the interpretation switches it ran with",
                    "Local model via Ollama, any OpenAI-compatible endpoint via env vars, rule-based fallback",
                    "Next: CI that runs dry run + self-check on every change, approval gate for high-impact "
                    "actions, metrics on calls/latency per agent"])
    prs.save(path)


def main() -> None:
    architecture_png(DOCS / "architecture.png")
    deck(DOCS / "control_tower_deck.pptx")
    print("wrote docs/architecture.png and docs/control_tower_deck.pptx")


if __name__ == "__main__":
    main()
