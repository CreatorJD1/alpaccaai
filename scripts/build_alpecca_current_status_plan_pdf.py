"""Build the current Alpecca status and master-phase handoff PDF."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "ALPECCA_CURRENT_STATUS_AND_PHASE_PLAN.pdf"

NAVY = colors.HexColor("#16212B")
INK = colors.HexColor("#26333D")
MUTED = colors.HexColor("#5E6B75")
LINE = colors.HexColor("#D7E0E5")
PANEL = colors.HexColor("#F4F7F8")
TEAL = colors.HexColor("#167A78")
TEAL_PALE = colors.HexColor("#DDF2EF")
AMBER = colors.HexColor("#B36A09")
AMBER_PALE = colors.HexColor("#FFF0D6")
RED = colors.HexColor("#B23B44")
RED_PALE = colors.HexColor("#FCE3E5")
GRAY = colors.HexColor("#66737D")
GRAY_PALE = colors.HexColor("#E9EEF1")
BLUE = colors.HexColor("#2E628E")
BLUE_PALE = colors.HexColor("#E2EEF7")


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=27, leading=32, textColor=NAVY, alignment=TA_LEFT,
            spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["BodyText"], fontName="Helvetica",
            fontSize=11, leading=16, textColor=MUTED, spaceAfter=18,
        ),
        "section": ParagraphStyle(
            "section", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=16, leading=20, textColor=NAVY, spaceBefore=8,
            spaceAfter=8,
        ),
        "subsection": ParagraphStyle(
            "subsection", parent=base["Heading3"], fontName="Helvetica-Bold",
            fontSize=11, leading=14, textColor=INK, spaceBefore=5,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9.3, leading=13.2, textColor=INK, spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "small", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8, leading=10.5, textColor=MUTED,
        ),
        "card_title": ParagraphStyle(
            "card_title", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=10.5, leading=13, textColor=NAVY,
        ),
        "card_body": ParagraphStyle(
            "card_body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8.5, leading=11.5, textColor=INK,
        ),
        "status": ParagraphStyle(
            "status", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=7.7, leading=9, alignment=TA_CENTER,
        ),
        "quote": ParagraphStyle(
            "quote", parent=base["BodyText"], fontName="Helvetica-Oblique",
            fontSize=9.2, leading=13, textColor=INK, leftIndent=10,
            rightIndent=10,
        ),
        "cover_kicker": ParagraphStyle(
            "cover_kicker", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=9, leading=12, textColor=TEAL, spaceAfter=8,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.5, leading=9, textColor=MUTED, alignment=TA_CENTER,
        ),
    }


STATUS = {
    "DONE": (TEAL_PALE, TEAL),
    "PARTIAL": (AMBER_PALE, AMBER),
    "BLOCKED": (RED_PALE, RED),
    "NOT STARTED": (GRAY_PALE, GRAY),
    "DEFERRED": (BLUE_PALE, BLUE),
}


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def status_chip(label: str, s) -> Table:
    bg, fg = STATUS[label]
    cell = p(label, ParagraphStyle("chip_" + label, parent=s["status"], textColor=fg))
    table = Table([[cell]], colWidths=[0.9 * inch], rowHeights=[0.25 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.4, fg),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return table


def phase_card(number: int, title: str, state: str, summary: str,
               gate: str, s) -> Table:
    header = Table(
        [[p(f"PHASE {number}", s["small"]), p(title, s["card_title"]), status_chip(state, s)]],
        colWidths=[0.7 * inch, 4.42 * inch, 0.95 * inch],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    content = [
        header,
        Spacer(1, 4),
        p(summary, s["card_body"]),
        Spacer(1, 3),
        p(f"<b>Exit gate:</b> {gate}", s["card_body"]),
    ]
    card = Table([[content]], colWidths=[6.18 * inch])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return card


def header_footer(canvas, doc):
    canvas.saveState()
    width, height = letter
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, height - 0.48 * inch, width - doc.rightMargin, height - 0.48 * inch)
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.setFillColor(TEAL)
    canvas.drawString(doc.leftMargin, height - 0.37 * inch, "ALPECCA - CURRENT STATUS AND MASTER PHASE PLAN")
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(width - doc.rightMargin, 0.35 * inch, f"Page {doc.page}")
    canvas.drawCentredString(width / 2, 0.35 * inch, "Generated 2026-07-10 - evidence-based planning status")
    canvas.restoreState()


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    s = styles()
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=letter,
        leftMargin=0.66 * inch, rightMargin=0.66 * inch,
        topMargin=0.72 * inch, bottomMargin=0.62 * inch,
        title="Alpecca Current Status and Master Phase Plan",
        author="Alpecca project",
    )
    story = []

    story.extend([
        Spacer(1, 0.52 * inch),
        p("CURRENT STATUS", s["cover_kicker"]),
        p("Alpecca Master Phase Plan", s["title"]),
        p(
            "A factual handoff and execution roadmap. This document separates "
            "implemented foundations from the master work that remains, starting "
            "with Phase 3: turn transactions and context isolation.",
            s["subtitle"],
        ),
        HRFlowable(width="100%", thickness=1.2, color=TEAL, spaceAfter=16),
    ])
    snapshot = [
        [p("Verified baseline", s["card_title"]), p("352 core tests passed; House HQ production build passed. Current branch: feat/vrm-preview.", s["card_body"])],
        [p("Local compute", s["card_title"]), p("Ryzen 5 6600H, approximately 24 GB DDR5-4800, RTX 3050 Laptop GPU with 4 GB VRAM. Live context remains 8K initially.", s["card_body"])],
        [p("Approved model", s["card_title"]), p("Ollama qwen3.5:9b. The retired legacy model path must not be restored or downloaded.", s["card_body"])],
        [p("Boundary", s["card_title"]), p("One authoritative CoreMind. No autonomous code edits, account actions, deletes, purchases, general OS changes, or extra instances.", s["card_body"])],
    ]
    table = Table(snapshot, colWidths=[1.35 * inch, 4.82 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), TEAL_PALE),
        ("BACKGROUND", (1, 0), (1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([table, Spacer(1, 18), p("How to read this plan", s["section"]),
                  p("There are two numbering systems in the project. The earlier agentic Stages 0-6 built useful foundations such as bounded tools, embedding backfill, constrained choice points, planner proposals, routines, and Mindpage. The master plan below is the remaining system-level dependency path. It begins at Phase 3 because Phase 0 is complete and the local authorization boundary is in place, while Phase 2 identity, singleton, and active-portal work remains a prerequisite slice.", s["body"]),
                  p("Status labels are conservative: PARTIAL means useful code exists but its live integration, safety, or proof is not complete. BLOCKED means it must remain unavailable until the stated gate passes.", s["quote"]),
                  PageBreak()])

    story.extend([
        p("Status Map", s["section"]),
        p("Master implementation sequence and current evidence", s["subtitle"]),
        phase_card(0, "Truth baseline and freeze", "DONE", "Encrypted recovery baseline, hardware correction, status diagrams, and documentation checkpoint are committed. Restore verification completed.", "Baseline remains reproducible and historical claims stay corrected.", s),
        Spacer(1, 8),
        phase_card(1, "Emergency security containment", "PARTIAL", "Local authorization and capability boundary have been committed. Public identity is preserved but is not authorization. Remote/public shell containment still requires final audit before being called DONE.", "Anonymous HTTP/WS denial, clean built shell, and no protected capability exposed through a public route.", s),
        Spacer(1, 8),
        phase_card(2, "Creator identity, singleton, active portal", "PARTIAL", "Protected local sessions exist, but authoritative Principal derivation, Windows named mutex, and portal lease/epoch fencing are not yet delivered.", "One CoreMind, one writable portal, stale epoch rejection, and creator identity derived only by server proof.", s),
        Spacer(1, 8),
        phase_card(3, "Turn transactions and context isolation", "NOT STARTED", "Next implementation phase. Replace global speaker/history semantics with immutable scoped turns, cancellation, commit barriers, and scope-partitioned retrieval/history/pages.", "No creator, guest, app, House HQ, or future Discord context crosses scope; timeouts cannot commit late work.", s),
        PageBreak(),
    ])

    story.extend([
        p("Execution Plan: Phases 4-6", s["section"]),
        p("These phases follow only after Phase 3 can prove turn and privacy isolation.", s["subtitle"]),
        phase_card(4, "Cue, commitment, and action closure", "NOT STARTED", "Create structured cues for correction, confirmation, reference, urgency, distress, questions, and action intent. Add durable commitments and tool receipts with explicit state transitions.", "Every claim of completion has a successful receipt; every promise is durable, proposed, or honestly declined.", s),
        Spacer(1, 8),
        phase_card(5, "Unified initiative and grounded affect", "PARTIAL", "Constrained choice, Soul arbitration, proactive behavior, and routines exist. They still need one per-scope relevance/cooldown/dedupe budget and evidence-backed affect updates.", "No duplicate outward event from unchanged evidence; ignored outreach backs off; uncertainty stays explicit.", s),
        Spacer(1, 8),
        phase_card(6, "Mindpage and resource coordinator", "PARTIAL", "Context ledger, paging, page faults, tiers, recall indexes, and pressure signals exist. Finish semantic negatives, buried-content indexing, overflow refusal/compaction, and single-flight optional work.", "No request exceeds the configured budget; optional background work cannot interfere with chat/TTS; larger context tiers pass measured laptop resource gates.", s),
        Spacer(1, 12),
        p("Phase 3 foundation already present", s["subsection"]),
        p("The smaller agentic Stage 3 is complete: local constrained choices handle living questions, same-rank Soul tie-breaks, and proactive yes/no plus seed selection. The seven Soul roles remain grounded symbolic readers, not parallel LLM instances. Compact background deliberation carries only focus and quantized validation scores; detailed reasoning remains for UI/review.", s["body"]),
        PageBreak(),
    ])

    story.extend([
        p("Execution Plan: Phases 7-10", s["section"]),
        phase_card(7, "Creator-approved pagefile broker", "BLOCKED", "Requires Phase 6 pressure evidence, a minimal elevated helper, fresh CreatorJD approval, live remeasurement, one-use proof, post-write readback, and a full audit trail.", "Only exact 4,096 MiB steps under the 55,296 MiB cap and 40 GiB free-space floor; no change without fresh approval.", s),
        Spacer(1, 8),
        phase_card(8, "Bounded recursive self-improvement", "PARTIAL", "Existing DB-backed tunables and evaluations are foundations. Align each trial with a consumed parameter, proposal, hypothesis, metric, exposure window, evidence, and exact rollback.", "No trial begins without policy approval; source, files, accounts, and OS remain outside self-modification.", s),
        Spacer(1, 8),
        phase_card(9, "Multimodal and source perception", "PARTIAL", "Adapters exist. Add scope-aware read-only source browsing, MIME/size/duration bounds, provenance, local-first vision/transcription, and explicit private-cloud consent.", "Files, images, and audio are cited with provenance; malformed input fails closed; grants stop when the session disconnects.", s),
        Spacer(1, 8),
        phase_card(10, "Discord presence and voice", "BLOCKED", "Do not enable participation, recursion, or broad capabilities until bridge envelopes, allowlists, scope isolation, rate limits, guest denial, and nonce-bound approvals are established.", "No cross-channel memory or leaked TTS; irrelevant messages remain silent; approvals cannot be spoofed in natural language.", s),
        PageBreak(),
    ])

    story.extend([
        p("Execution Plan: Phases 11-14", s["section"]),
        phase_card(11, "Creator contact and notification outbox", "DEFERRED", "Plan app Web Push first, Discord DM second, SMS third, and phone calls only by explicit opt-in. Use a durable idempotent outbox with quotas, acknowledgement, retries, and secret-backed destinations.", "One event despite retries/restarts; acknowledgement stops escalation; no channel silently seizes the active portal.", s),
        Spacer(1, 8),
        phase_card(12, "V4 embodiment behavior and physics", "PARTIAL", "V4 is live with 74 spring joints and 22 colliders. Complete root/hip cleanup, 1.70 m calibration, posed-sole grounding, expression reset, one-shot gestures, idle behavior, collider tuning, and turntable QA.", "Ten-minute physics soak has no instability or persistent clipping; boots and scale pass four-angle design-lock review.", s),
        Spacer(1, 8),
        phase_card(13, "Cloud egress and Mindscape continuity", "BLOCKED", "Cloud must use classified, allowlisted, audited egress. Mindscape needs fail-closed access, signed/versioned bounded snapshots, replay protection, and CreatorJD-approved transactional restore.", "Cloud loss leaves local conversation available; no private payload leaves without consent; cloud never runs a second active CoreMind.", s),
        Spacer(1, 8),
        phase_card(14, "Release soak and living documentation", "NOT STARTED", "Run fresh-DB, concurrent actor, timeout, resource, Discord canary, Mindscape failover, and V4 animation drills. Deploy only after evidence updates the diagrams and docs.", "No context leakage, hidden external action, duplicate initiative, cloud dependency, or unsupported status claim in release evidence.", s),
        Spacer(1, 14),
        p("Current handoff boundary", s["section"]),
        p("The working tree intentionally retains unrelated changes: House HQ VRM embodiment work, config.py work, and untracked CreatorContact/SystemPressure scaffolds. Do not overwrite, revert, or silently wire them into new phases. Existing keys/tokens and the public Alpecca identity remain untouched; phone/contact security is deferred until after the staged plan.", s["body"]),
        Spacer(1, 8),
        p("Source of truth: PROJECT_CONTEXT.md and HANDOFF.md. Detailed sequencing: docs/ALPECCA_MASTER_PLAN.md. Latest handoff checkpoint: b4640d9 on feat/vrm-preview.", s["small"]),
    ])

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    print(OUTPUT)


if __name__ == "__main__":
    build()
