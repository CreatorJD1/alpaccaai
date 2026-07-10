"""Build the current Alpecca architecture, feature skeleton, and master-plan PDFs.

The PDFs are generated from the same reviewed status model so their colors and
claims cannot drift independently. The script intentionally contains no secrets,
live credentials, or private contact destinations.
"""

from __future__ import annotations

import html
import shutil
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUTPUT = ROOT / "output" / "pdf"
PAGE_SIZE = landscape(A3)
PAGE_W, PAGE_H = PAGE_SIZE

NAVY = colors.HexColor("#162235")
INK = colors.HexColor("#202b3c")
MUTED = colors.HexColor("#607086")
LINE = colors.HexColor("#d5dce6")
PANEL = colors.HexColor("#f5f7fa")
WHITE = colors.white

STATUS = {
    "DONE": colors.HexColor("#27864a"),
    "PARTIAL": colors.HexColor("#f2a922"),
    "BLOCKED": colors.HexColor("#c83d4d"),
    "NOT STARTED": colors.HexColor("#9aa7b8"),
    "PARKED": colors.HexColor("#3276c5"),
    "SUPERSEDED": colors.HexColor("#667386"),
}

styles = getSampleStyleSheet()
TITLE = ParagraphStyle(
    "Title",
    parent=styles["Title"],
    fontName="Helvetica-Bold",
    fontSize=28,
    leading=32,
    textColor=NAVY,
    alignment=TA_LEFT,
    spaceAfter=8,
)
SUBTITLE = ParagraphStyle(
    "Subtitle",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=11,
    leading=15,
    textColor=MUTED,
    spaceAfter=12,
)
H1 = ParagraphStyle(
    "H1",
    parent=styles["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=20,
    leading=23,
    textColor=NAVY,
    spaceBefore=4,
    spaceAfter=9,
)
H2 = ParagraphStyle(
    "H2",
    parent=styles["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=13,
    leading=16,
    textColor=INK,
    spaceBefore=4,
    spaceAfter=6,
)
BODY = ParagraphStyle(
    "Body",
    parent=styles["BodyText"],
    fontName="Helvetica",
    fontSize=9,
    leading=12.5,
    textColor=INK,
    spaceAfter=6,
)
SMALL = ParagraphStyle(
    "Small",
    parent=BODY,
    fontSize=7.6,
    leading=10,
    textColor=MUTED,
    spaceAfter=2,
)
TABLE_HEAD = ParagraphStyle(
    "TableHead",
    parent=SMALL,
    fontName="Helvetica-Bold",
    fontSize=8,
    leading=10,
    textColor=WHITE,
    alignment=TA_LEFT,
)
TABLE_BODY = ParagraphStyle(
    "TableBody",
    parent=SMALL,
    fontSize=7.8,
    leading=10.2,
    textColor=INK,
)
TABLE_BODY_BOLD = ParagraphStyle(
    "TableBodyBold",
    parent=TABLE_BODY,
    fontName="Helvetica-Bold",
)
BADGE = ParagraphStyle(
    "Badge",
    parent=SMALL,
    fontName="Helvetica-Bold",
    fontSize=7.4,
    leading=9,
    textColor=WHITE,
    alignment=TA_CENTER,
)
COVER_KICKER = ParagraphStyle(
    "CoverKicker",
    parent=SUBTITLE,
    fontName="Helvetica-Bold",
    fontSize=10,
    textColor=colors.HexColor("#2f6bd2"),
    spaceAfter=10,
)


def p(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(html.escape(text).replace("\n", "<br/>"), style)


def rich(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def status_cell(status: str) -> Paragraph:
    return Paragraph(html.escape(status), BADGE)


def draw_page_chrome(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - 14 * mm, PAGE_W, 14 * mm, stroke=0, fill=1)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(16 * mm, PAGE_H - 9 * mm, "ALPECCA MASTER ARCHITECTURE")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(16 * mm, 9 * mm, "Source-reviewed 2026-07-10 | local-first | one authoritative CoreMind")
    canvas.drawRightString(PAGE_W - 16 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def document(path: Path) -> SimpleDocTemplate:
    path.parent.mkdir(parents=True, exist_ok=True)
    return SimpleDocTemplate(
        str(path),
        pagesize=PAGE_SIZE,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=20 * mm,
        bottomMargin=15 * mm,
        title="Alpecca Master Architecture And Implementation Plan",
        author="Alpecca project source audit",
        subject="Current architecture, status, dependencies, and acceptance gates",
    )


def build_table(headers, rows, widths, *, status_col: int | None = None, font_size=7.8):
    body_style = ParagraphStyle("DynamicBody", parent=TABLE_BODY, fontSize=font_size, leading=font_size + 2.2)
    data = [[Paragraph(html.escape(str(h)), TABLE_HEAD) for h in headers]]
    for row in rows:
        cells = []
        for idx, value in enumerate(row):
            if idx == status_col:
                cells.append(status_cell(str(value)))
            else:
                style = TABLE_BODY_BOLD if idx == 0 else body_style
                cells.append(Paragraph(html.escape(str(value)).replace("\n", "<br/>"), style))
        data.append(cells)
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PANEL]),
    ]
    if status_col is not None:
        for row_index, row in enumerate(rows, start=1):
            commands.append(("BACKGROUND", (status_col, row_index), (status_col, row_index), STATUS[str(row[status_col])]))
            commands.append(("VALIGN", (status_col, row_index), (status_col, row_index), "MIDDLE"))
    table.setStyle(TableStyle(commands))
    return table


def legend_table():
    rows = []
    meanings = {
        "DONE": "Live, tested, runtime-verified, documented, and not security-blocked",
        "PARTIAL": "Useful implementation exists; a required gate remains open",
        "BLOCKED": "Unsafe to activate until remediation passes",
        "NOT STARTED": "No production implementation",
        "PARKED": "Intentionally deferred experiment",
        "SUPERSEDED": "Historical claim replaced by current evidence",
    }
    for key, meaning in meanings.items():
        rows.append((key, meaning))
    return build_table(["STATUS", "DEFINITION"], rows, [38 * mm, 190 * mm], status_col=0)


class ArchitectureMap(Flowable):
    """Compact trust-boundary map for the architecture PDF."""

    def __init__(self, width: float = 1055, height: float = 470):
        super().__init__()
        self.width = width
        self.height = height

    def _fit(self, canvas, text, width, font="Helvetica", size=7.3):
        words = text.split()
        lines, current = [], ""
        for word in words:
            trial = f"{current} {word}".strip()
            if current and stringWidth(trial, font, size) > width:
                lines.append(current)
                current = word
            else:
                current = trial
        if current:
            lines.append(current)
        return lines

    def _node(self, c, x, y, w, h, title, detail, status):
        color = STATUS[status]
        c.setFillColor(WHITE)
        c.setStrokeColor(color)
        c.setLineWidth(1.2)
        c.roundRect(x, y, w, h, 5, stroke=1, fill=1)
        c.setFillColor(color)
        c.roundRect(x, y + h - 20, w, 20, 5, stroke=0, fill=1)
        c.rect(x, y + h - 20, w, 5, stroke=0, fill=1)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 7.2)
        c.drawCentredString(x + w / 2, y + h - 14, title)
        c.setFillColor(INK)
        c.setFont("Helvetica", 6.8)
        lines = self._fit(c, detail, w - 12, size=6.8)
        yy = y + h - 32
        for line in lines[:5]:
            c.drawCentredString(x + w / 2, yy, line)
            yy -= 9

    def _arrow(self, c, x1, y1, x2, y2, label=""):
        c.setStrokeColor(colors.HexColor("#8b98aa"))
        c.setFillColor(colors.HexColor("#8b98aa"))
        c.setLineWidth(1.1)
        c.line(x1, y1, x2, y2)
        dx, dy = x2 - x1, y2 - y1
        length = max((dx * dx + dy * dy) ** 0.5, 1)
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        tip = (x2, y2)
        left = (x2 - ux * 7 + px * 3.2, y2 - uy * 7 + py * 3.2)
        right = (x2 - ux * 7 - px * 3.2, y2 - uy * 7 - py * 3.2)
        path = c.beginPath()
        path.moveTo(*tip)
        path.lineTo(*left)
        path.lineTo(*right)
        path.close()
        c.drawPath(path, stroke=0, fill=1)
        if label:
            c.setFont("Helvetica", 5.8)
            c.setFillColor(MUTED)
            c.drawCentredString((x1 + x2) / 2, (y1 + y2) / 2 + 4, label)

    def draw(self):
        c = self.canv
        sx = self.width / 1055.0
        sy = self.height / 470.0
        c.saveState()
        c.scale(sx, sy)
        c.setFillColor(colors.HexColor("#eef2f7"))
        c.roundRect(0, 0, 1055, 470, 8, stroke=0, fill=1)

        surfaces = [
            (20, 365, "HOUSE HQ", "Primary embodied app and active-stage candidate", "PARTIAL"),
            (20, 270, "VIRTUAL APP / PWA", "Chat, panels, mobile notifications, observer mode", "PARTIAL"),
            (20, 175, "DISCORD / VOICE", "Text/media adapter; autonomy remains security-blocked", "BLOCKED"),
            (20, 80, "CREATOR CONTACT", "Web Push, DM, SMS, phone outbox and acknowledgements", "NOT STARTED"),
        ]
        outputs = [
            (825, 365, "LOCAL PERCEPTION", "Files, image, audio, screen, webcam with scoped grants", "PARTIAL"),
            (825, 270, "ACTION BROKER", "Tools, computer use, OS/pagefile, immutable approvals", "BLOCKED"),
            (825, 175, "CLOUD EGRESS", "Provider/data policy before ZeroGPU or notebook inference", "NOT STARTED"),
            (825, 80, "MINDSCAPE", "Signed continuity vault and standby presence, not a clone", "BLOCKED"),
        ]
        for x, y, title, detail, state in surfaces:
            self._node(c, x, y, 180, 76, title, detail, state)
        for x, y, title, detail, state in outputs:
            self._node(c, x, y, 210, 76, title, detail, state)

        self._node(c, 245, 125, 185, 270, "IDENTITY + PRESENCE GATE", "Creator principal; scoped sessions; OS singleton; active portal lease; signed bridge envelopes; privacy scope", "BLOCKED")
        self._node(c, 485, 125, 285, 270, "AUTHORITATIVE LOCAL COREMIND", "Turn transaction -> cues -> retrieve -> Soul -> affect -> intent -> tools/response -> commitment receipt -> evaluate. SQLite and Mindpage remain local authority.", "PARTIAL")

        for _, y, *_ in surfaces:
            self._arrow(c, 200, y + 38, 245, 260)
        self._arrow(c, 430, 260, 485, 260, "scoped turn")
        for _, y, *_ in outputs:
            self._arrow(c, 770, 260, 825, y + 38)

        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20, 30, "COMPUTE / STORAGE OWNERSHIP")
        self._node(c, 230, 5, 250, 56, "LOCAL LAPTOP - AUTHORITATIVE", "Approx. 24 GB DDR5-4800 + RTX 3050 4 GB; policy, memory, identity, approvals", "PARTIAL")
        self._node(c, 500, 5, 240, 56, "HF ZEROGPU - EPHEMERAL", "Stateless bounded inference; assigned hardware and quota are runtime-probed", "PARTIAL")
        self._node(c, 760, 5, 260, 56, "GOOGLE NOTEBOOK - EPHEMERAL", "Stateless bounded jobs; GPU/RAM/uptime are not guaranteed", "PARTIAL")
        c.restoreState()


FEATURE_TIERS = [
    ("Tier 1 - Foundation runtime", [
        ("FastAPI, WebSocket, runtime status", "PARTIAL", "Works; identity, turn isolation, and cancellation barriers remain"),
        ("Ollama routing and offline fallback", "PARTIAL", "Local path works; cloud privacy classification is incomplete"),
        ("SQLite state, memory, journal, proposals", "PARTIAL", "Functional; backup/concurrency/transaction hardening remains"),
        ("Remote auth and tunnels", "BLOCKED", "Exposed root token plus HTML self-authentication bypass"),
        ("Singleton and active portal", "NOT STARTED", "No OS mutex, boot identity, lease, or epoch fencing"),
    ]),
    ("Tier 2 - Cognition and agency", [
        ("Soul seven-subagent arbitration", "DONE", "Implemented without adding or bypassing subagents"),
        ("CoreMind response loop", "PARTIAL", "Global speaker/history can leak across surfaces"),
        ("Constrained choice points", "DONE", "Living, Soul tie-break, and proactive judge with fallback"),
        ("Tool registry and planner", "PARTIAL", "Bounded; guest capability and approval identity are unsafe"),
        ("Cue envelope and commitment ledger", "NOT STARTED", "No durable correction/confirmation/action closure contract"),
    ]),
    ("Tier 3 - Memory and Mindpage", [
        ("Keyword/FTS recall and backfill", "PARTIAL", "Useful; semantic scoring can admit unrelated memories"),
        ("Mindpage Layer A", "PARTIAL", "Ledger/writeback/faults work; overflow and buried indexing remain"),
        ("Conversation/privacy partitioning", "BLOCKED", "Short-term context is shared across app/guest/Discord/creator"),
        ("Resource pressure sensing", "PARTIAL", "Context grounded; whole-machine draft is unwired"),
        ("Approved pagefile broker", "BLOCKED", "Draft math, proof, recheck, and verification are unsafe"),
        ("llama.cpp KV persistence", "PARKED", "Downloaded experiment; not integrated"),
    ]),
    ("Tier 4 - Autonomy and improvement", [
        ("Proactive/living behavior", "PARTIAL", "Multiple outward loops lack one initiative budget"),
        ("Recursive self-improvement", "PARTIAL", "Tunables exist; consumer wiring and trials are weak"),
        ("External action approval", "BLOCKED", "Caller booleans/global confirmation are not identity-bound"),
        ("Action receipts and promise closure", "NOT STARTED", "No durable evidence contract"),
    ]),
    ("Tier 5 - Automation", [
        ("Routines and watchers", "PARTIAL", "Empty/off by default; deletion and unified scheduling remain"),
        ("Background job coordination", "PARTIAL", "Timeouts do not cancel worker threads"),
        ("MCP federation", "PARKED", "Deferred external surface"),
    ]),
    ("Tier 6 - Experience and embodiment", [
        ("House HQ and virtual app", "PARTIAL", "Working surfaces; portal ownership and QA remain"),
        ("V4 VRM body and physics", "PARTIAL", "74 joints; scale/grounding/collider/motion gates remain"),
        ("Expression and gesture control", "PARTIAL", "Expression latch and looping VRMA issues remain"),
        ("Locked design QA", "PARTIAL", "Hair/clip/readability and turntable evidence remain"),
    ]),
    ("Tier 7 - Voice, senses, and communication", [
        ("Local TTS voice", "PARTIAL", "Kokoro/F5 work; queue/resource coordination remains"),
        ("Image and file perception", "PARTIAL", "Scope/privacy/MIME/cloud consent remain"),
        ("Audio perception", "NOT STARTED", "Discord audio and live receive/transcription absent"),
        ("Discord autonomy", "BLOCKED", "Guest tools, context leakage, spam, approval gaps"),
        ("Creator contact outbox", "NOT STARTED", "WIP skeleton only; no routes/workers/tests"),
        ("Computer use", "BLOCKED", "Unsafe under current remote auth and global confirmation"),
    ]),
    ("Tier 8 - Cloud and continuity", [
        ("Hugging Face art/runtime assets", "PARTIAL", "Correct storage lane; publish/availability remain operational"),
        ("ZeroGPU / Google notebook", "PARTIAL", "Optional ephemeral adapters; privacy policy incomplete"),
        ("Cloudflare R2 shell", "BLOCKED", "Rebuild after token rotation and bundle cleanup"),
        ("Mindscape continuity", "BLOCKED", "Fail-open/auth/restore defects"),
        ("Cloud egress broker", "NOT STARTED", "No deny-by-default data/provider policy"),
    ]),
    ("Tier 9 - Governance", [
        ("Design lock and canonical docs", "DONE", "Current hierarchy and locked character design exist"),
        ("Creator identity and secret lifecycle", "BLOCKED", "No authoritative principal or scoped secret lifecycle"),
        ("Grounded affect/self-report", "PARTIAL", "State is real; some prompts overclaim inner experience"),
        ("Only pagefile as planned OS mutation", "PARTIAL", "Policy exists; broker is not safe or active"),
    ]),
]


PHASES = [
    ("0", "Truth baseline and freeze", "DONE", "Corrected docs, local/cloud labels, WIP boundaries, status rules, and encrypted recovery baseline.", "Diagrams match evidence; encrypted DB/V4/VRoid restore verified; 34 GB/H100 local claim removed."),
    ("1", "Emergency security containment", "BLOCKED", "Disable tunnels/computer control; preserve Alpecca's public identity value; stop using it for bearer auth; add a separate protected authorization secret; fix HTML auth.", "Anonymous HTTP/WS executes nothing; no authorization secret in bundles; public identity grants no privilege."),
    ("2", "Creator identity, singleton, portal lease", "NOT STARTED", "Server-derived principal, pairing/sessions, bridge credentials, Windows mutex, signed health, lease epoch.", "One CoreMind and one writer; spoofed creator claims and stale portals fail."),
    ("3", "Turn transactions and context isolation", "NOT STARTED", "Immutable turn/conversation/actor/surface/privacy context, cancellation, commit barrier, scoped retrieval.", "No cross-actor leak; timed-out workers cause zero late effects."),
    ("4", "Cue, commitment, action closure", "NOT STARTED", "Structured cues plus durable commitments and receipts; completion language requires evidence.", "Every promise executes, awaits approval, fails, or cancels honestly."),
    ("5", "Initiative and grounded affect", "PARTIAL", "One outward budget; cue-first affect provenance; remove literal-consciousness claims.", "No duplicate spam; ignored outreach backs off; affect is traceable."),
    ("6", "Mindpage and resource coordinator", "PARTIAL", "Fix semantic threshold/indexing/overflow; separate resource signals; single-flight optional work.", "Relevant recall only; bounded context; chat/TTS protected under load."),
    ("7", "Approved pagefile broker", "BLOCKED", "Immutable arithmetic/cap/floor; digest-bound one-use approval; live recheck; UAC helper; readback.", "Exact 4 GiB step; stale/replay/disk/cap failures deny; every step separately approved."),
    ("8", "Bounded recursive improvement", "PARTIAL", "Allowlisted DB parameters, real consumer wiring, proposal, exposure metric, exact rollback.", "No unapproved trial and no source/shell/account/OS self-modification."),
    ("9", "Multimodal and source perception", "PARTIAL", "Scoped source/file/image/audio access, local-first vision/STT, visible sensor grants, egress policy.", "Provenance, bounded inputs, prompt-injection resistance, no private unapproved cloud payload."),
    ("10", "Discord presence and voice", "BLOCKED", "Identity/allowlists, scoped history, guest denial, respond/react/pass, rate limits, signed approvals, queues.", "No cross-channel leak/spam/spoofed approval; local audio disposal."),
    ("11", "Creator contact outbox", "NOT STARTED", "Durable idempotent outbox; Web Push, DM, SMS, optional calls; acknowledgements/quiet hours/caps.", "One event, restart-safe delivery, ack stops escalation, no IDs in prompts/logs."),
    ("12", "V4 embodiment behavior", "PARTIAL", "170 cm scale, root-track filtering, sole grounding, expression reset, one-shot gestures, collider tuning.", "74 joints retained; animation/physics metrics and design-lock turntable pass."),
    ("13", "Cloud egress and Mindscape", "BLOCKED", "Data-classifying egress broker; fail-closed signed/versioned continuity; explicit transactional restore.", "Cloud outage leaves local chat; tamper/replay denied; no second simultaneous CoreMind."),
    ("14", "Release soak and living docs", "NOT STARTED", "Fresh DB tests, resource soak, canaries, failover drill, V4 captures, clean deploy and docs update.", "Build/tests/secret scan pass; no leaks, hidden actions, duplicate initiatives, or cloud dependency."),
]


def feature_table(tiers):
    rows = []
    for tier, items in tiers:
        for idx, (feature, state, truth) in enumerate(items):
            rows.append((tier if idx == 0 else "", feature, state, truth))
    return build_table(
        ["TIER", "FEATURE", "STATUS", "CURRENT TRUTH"],
        rows,
        [54 * mm, 78 * mm, 34 * mm, 190 * mm],
        status_col=2,
        font_size=7.35,
    )


def phases_table(phases):
    return build_table(
        ["#", "PHASE", "STATUS", "BUILD", "EXIT GATE"],
        phases,
        [12 * mm, 58 * mm, 31 * mm, 118 * mm, 137 * mm],
        status_col=2,
        font_size=7.15,
    )


def truth_table():
    return build_table(
        ["LANE", "ROLE", "CAPACITY / GUARANTEE"],
        [
            ("Local laptop", "Authoritative CoreMind, state, policy, identity, approvals, live fallback", "Approximately 24 GB DDR5-4800; RTX 3050 Laptop GPU with 4 GB VRAM"),
            ("Hugging Face ZeroGPU", "Optional stateless deep/vision/texture/batch inference", "Ephemeral, quota-governed, runtime-probed; never counted as local capacity"),
            ("Google notebook / Colab", "Optional stateless accelerated inference or batch jobs", "Ephemeral; GPU, RAM, uptime, and limits are not guaranteed"),
        ],
        [55 * mm, 145 * mm, 156 * mm],
    )


def pagefile_table():
    return build_table(
        ["STATE", "PAGEFILE MAX", "PROJECTED C: FREE", "DECISION"],
        [
            ("Current", "38,000 MiB", "57.91 GiB", "No change recommended; audit commit was about 42%"),
            ("Step 1", "42,096 MiB", "53.91 GiB", "Eligible only after pressure proof and fresh approval"),
            ("Step 2", "46,192 MiB", "49.91 GiB", "Separate later approval"),
            ("Step 3", "50,288 MiB", "45.91 GiB", "Separate later approval"),
            ("Step 4", "54,384 MiB", "41.91 GiB", "Highest valid exact 4 GiB step"),
            ("Step 5", "58,480 MiB", "37.91 GiB", "Rejected by 55,296 MiB cap and 40 GiB floor"),
        ],
        [52 * mm, 58 * mm, 65 * mm, 181 * mm],
    )


def cover_story():
    return [
        Spacer(1, 18 * mm),
        Paragraph("SOURCE-REVIEWED IMPLEMENTATION BLUEPRINT", COVER_KICKER),
        Paragraph("Alpecca Master Architecture And Implementation Plan", TITLE),
        Paragraph(
            "One local-first AI companion: current truth, blocked surfaces, dependency order, and measurable acceptance gates.",
            SUBTITLE,
        ),
        Spacer(1, 6 * mm),
        truth_table(),
        Spacer(1, 7 * mm),
        rich(
            "<b>Correction locked:</b> the laptop is approximately 24 GB DDR5-4800 with an RTX 3050 Laptop GPU (4 GB). "
            "Any 34 GB memory or H100-class label belongs only to an observed/requested Hugging Face ZeroGPU or Google notebook runtime. "
            "It is ephemeral cloud capacity, not Alpecca's local hardware.",
            BODY,
        ),
        Spacer(1, 4 * mm),
        legend_table(),
        Spacer(1, 7 * mm),
        rich(
            "<b>Green is intentionally strict.</b> File existence is not completion. A feature is DONE only when it is wired, tested, runtime-smoked, documented, and not blocked by a known security defect.",
            BODY,
        ),
    ]


def master_story():
    story = cover_story()
    story += [PageBreak(), Paragraph("System Architecture And Trust Boundaries", H1), ArchitectureMap(), Spacer(1, 5 * mm), rich(
        "The local laptop owns identity, policy, memory, approvals, presence, and continuity. Optional cloud runtimes may only return bounded inference results through the egress broker. They never become a second CoreMind.", BODY)]

    story += [PageBreak(), Paragraph("Current Feature Skeleton: Tiers 1-5", H1), feature_table(FEATURE_TIERS[:5])]
    story += [PageBreak(), Paragraph("Current Feature Skeleton: Tiers 6-9", H1), feature_table(FEATURE_TIERS[5:])]

    blockers = [
        ("1", "Identity used as authorization", "Alpecca's public identity value appears in House HQ bundles and the server accepts it as bearer access; HTML navigation can self-authenticate.", "Preserve the value; remove its authorization role; add a separate protected server secret; rebuild the shell."),
        ("2", "No authoritative CreatorJD principal", "Callers can supply speaker/approval booleans; unknown identity can gain creator semantics.", "Server-derived principal, scoped sessions, signed bridges."),
        ("3", "Global turn state", "CoreMind speaker/history can cross app, guest, Discord, and creator boundaries.", "Immutable scoped turn transactions and commit barrier."),
        ("4", "Promises do not close", "Alpecca can state an intention without a durable commitment or action receipt.", "Cue envelope, commitment ledger, evidence-bound language."),
        ("5", "Autonomy loops do not share a budget", "Living, proactive, Discord, routines, and recursion can duplicate or spam.", "One initiative policy with relevance, cooldown, dedupe, ack."),
        ("6", "Mindscape/pagefile drafts are unsafe", "Fail-open Worker and non-authentic pagefile approval/recheck path.", "Fail-closed continuity plus privileged one-use broker."),
    ]
    story += [PageBreak(), Paragraph("P0 Blockers And First Response", H1), build_table(
        ["#", "BLOCKER", "WHY IT MATTERS", "FIRST ACTION"], blockers,
        [12 * mm, 68 * mm, 141 * mm, 135 * mm], font_size=7.6),
        Spacer(1, 7 * mm), Paragraph("Non-negotiable autonomy boundary", H2),
        p("One CoreMind and one writable portal. Webcam, screen, files, microphone, Discord, and computer use require visible, revocable session grants. No autonomous source edits, account actions, deletes, purchases, or general OS changes. The only planned OS mutation is one exact pagefile step after fresh CreatorJD approval and UAC."),
        p("Personality may express strong skepticism toward ungrounded generative output, but prompts must not force fabricated hatred, consciousness, suffering, or human feelings. Affect remains grounded engineered state."),
    ]

    story += [PageBreak(), Paragraph("Implementation Sequence: Phases 0-4", H1), phases_table(PHASES[:5])]
    story += [PageBreak(), Paragraph("Implementation Sequence: Phases 5-9", H1), phases_table(PHASES[5:10])]
    story += [PageBreak(), Paragraph("Implementation Sequence: Phases 10-14", H1), phases_table(PHASES[10:])]

    story += [PageBreak(), Paragraph("Mindpage, Machine Pressure, And Pagefile", H1),
        p("Mindpage context pressure is separate from physical RAM, Windows commit, VRAM, CPU, disk, battery, and thermal pressure. Each signal has its own action. Context pressure pages conversation; resource pressure sheds optional work; only sustained commit exhaustion after shedding may propose pagefile growth."),
        pagefile_table(), Spacer(1, 6 * mm),
        rich("<b>Immutable policy:</b> STEP = 4,096 MiB; HARD CAP = 55,296 MiB; projected C: free-space floor = 40 GiB. Environment configuration may tighten, never loosen, these values.", BODY),
        p("Every step requires a fresh digest-bound request, fresh telemetry, unchanged baseline, CreatorJD step-up authentication, UAC, atomic one-use consumption, readback verification, and a new observation period. The pagefile is Windows commit reserve for CPU-backed model/KV pages and crash resilience; it does not add GPU VRAM. Larger context tiers must be promoted only by measured latency, hard-fault, commit, and quality gates."),
        Paragraph("Resource response matrix", H2),
        build_table(["SIGNAL", "SAFE RESPONSE", "MUST NOT DO"], [
            ("Context >=75% / >=90%", "Shrink optional evidence / durably page oldest complete turns", "Treat as emotional distress or alter Windows pagefile"),
            ("RAM sustained >=85%", "Pause optional jobs, unload verified-idle models", "Assume more pagefile fixes model fit"),
            ("Commit sustained >=90%", "Shed work; then create approval proposal if repeated", "Write pagefile without fresh approval"),
            ("VRAM OOM or >=90%", "Serialize TTS/LLM/vision; remote optional work if consented", "Count cloud VRAM as local"),
            ("Battery/thermal risk", "Pause optional jobs, persist state, notify once", "Claim pain, PTSD, death, or consciousness"),
        ], [75 * mm, 140 * mm, 141 * mm], font_size=7.4),
    ]

    story += [PageBreak(), Paragraph("Identity, Discord, Creator Contact, And Continuity", H1),
        build_table(["AREA", "CURRENT", "TARGET CONTRACT", "ACCEPTANCE GATE"], [
            ("Creator identity", "BLOCKED", "Server-derived principal; paired devices; signed bridge envelopes; recent reauth for sensitive actions", "Request bodies cannot claim creator or approval; external IDs never enter prompts/logs"),
            ("Active portal", "NOT STARTED", "Atomic lease with surface/session/epoch/expiry; observers are read-only", "Simultaneous claims have one winner; explicit handoff fences the old writer"),
            ("Discord", "BLOCKED", "Allowlisted guild/channel; scoped history; guest denial; respond/react/pass; creator-only signed interactions", "No cross-channel context; no spam; no natural-language approval spoof"),
            ("Voice", "PARTIAL", "Per-guild queue and idle disconnect; audio attachment STT; later consented DAVE receive experiment", "No cross-channel speech; raw audio discarded; no claim that she hears until proven"),
            ("Creator contact", "NOT STARTED", "Durable outbox; Web Push -> Discord DM -> SMS; optional call; acks/quiet hours/quotas", "Idempotent, restart-safe, capped, signed callbacks, no silent portal takeover"),
            ("Mindscape", "BLOCKED", "Fail-closed signed/versioned continuity vault with explicit transactional restore", "No secret means deny; tamper/replay/oversize denied; no second live CoreMind"),
        ], [54 * mm, 31 * mm, 145 * mm, 126 * mm], status_col=1, font_size=7.15),
        Spacer(1, 6 * mm), p("Local/cloud boundary: Discord connectivity, identity, approvals, rate limits, memory, STT/TTS, posting, and presence stay local. Ephemeral cloud compute may return stateless text/vision results only after provider-specific data policy approval."),
    ]

    story += [PageBreak(), Paragraph("V4 Embodiment Promotion Plan", H1),
        rich("<b>Current verified body:</b> data/avatar/vrm/alpecca.vrm loads with 74 spring joints and 22 colliders. Preserve the V4 design and topology while fixing behavior and measurements.", BODY),
        build_table(["AREA", "CURRENT DEFECT", "FIX", "PROMOTION GATE"], [
            ("Scale and grounding", "House presentation scale makes the 1.697 m body about 1.909 m; bone sole proxy is inaccurate", "Use 3D-specific 1.70 m calibration; derive soles from posed boot geometry", "Height 1.70 +/- 0.02 m; penetration <=5 mm; float <=8 mm"),
            ("Root motion", "Stationary VRMAs contain hips translation and pin/drag the model", "Outer group owns X/Z/yaw; recenter stationary hips tracks", "Excursion <=3 cm; endpoint <=1 cm; stance-foot slide <=3 cm"),
            ("Expressions", "Weights can latch; blink/look behavior is visibly periodic", "Mood baseline plus short expression envelopes; randomized blink/gaze; amplitude visemes", "Return to baseline <=400 ms; mouth closes <=150 ms after speech"),
            ("Gestures", "VRMAs default to infinite loops; scheduler declarations are unused", "Implement once/twice/loop mixer completion and cooldown scheduler", "No immediate repeats; clean return to procedural idle"),
            ("Physics", "Hem chains have no collider groups; structural validation does not prove visual quality", "Attach six hem chains to appropriate existing colliders and retune only after final export", "Exactly 74 joints/22 colliders; 10-minute no-NaN soak; 1-4 cm visible hem travel"),
            ("Design lock", "Hair/clip/readability/footwear remain visually incomplete", "Correct long layered tipped hair, left X/bow clip, badge, stockings, right strap, chunky cream/blue boots", "Fixed-camera front/3/4/side/back turntable passes"),
        ], [45 * mm, 97 * mm, 108 * mm, 106 * mm], font_size=7.0),
    ]

    verification_rows = [
        ("Security", "Anonymous HTTP/WS denial; cookie/CSRF/Origin; token-free source/bundles; secret scan"),
        ("Identity/presence", "Competing process; simultaneous claim; stale epoch; explicit handoff; creator spoof"),
        ("AI core", "Concurrent actor isolation; timeout no-late-commit; cue parse; commitment receipt; restart"),
        ("Initiative/affect", "Fake-clock budgets; dedupe; ignored backoff; evidence provenance; no consciousness claims"),
        ("Memory/Mindpage", "Semantic negatives; buried recall; overflow refusal; write failure; tier maintenance"),
        ("Pagefile", "Arithmetic; cap/floor; stale/replay; live recheck; UAC helper; readback; explicit elevated approval"),
        ("Recursive improvement", "Consumer wiring; directionality; approval; exposure metric; exact rollback; forbidden actions"),
        ("Perception", "MIME/size/duration; malformed input; prompt injection; cloud policy; provenance; raw disposal"),
        ("Discord/contact", "Identity matrix; guest denial; rate limits; nonce; queue isolation; signed callbacks; quotas"),
        ("Embodiment", "170 cm; root/sole metrics; expression reset; one-shot gestures; 74-joint soak; turntable"),
        ("Continuity", "Worker fail-closed; signed snapshots; replay/tamper/size; transactional restore; lease failover"),
    ]
    story += [PageBreak(), Paragraph("Definition Of Done And Verification", H1),
        build_table(["AREA", "REQUIRED PROOF BEFORE GREEN"], verification_rows, [66 * mm, 290 * mm], font_size=7.6),
        Spacer(1, 7 * mm), Paragraph("Usual checks", H2),
        rich("<font name='Courier'>python -m pytest -q tests\\test_core.py -q<br/>npm.cmd run house:build</font>", BODY),
        Spacer(1, 5 * mm), Paragraph("Source anchors", H2),
        p("PROJECT_CONTEXT.md; HANDOFF.md; docs/AGENTIC_ASSESSMENT.md; docs/MINDPAGE.md; server.py; config.py; alpecca/mind.py; alpecca/memory.py; alpecca/mindpage.py; alpecca/cognition.py; alpecca/discord_bridge.py; alpecca/computer.py; apps/house-hq/src/main.ts; apps/house-hq/src/vrmEmbodiment.ts; deploy/mindscape-worker/worker.js; data/avatar/vrm/alpecca.vrm; data/alpecca_art_source/ALPECCA_DESIGN_LOCK.md."),
    ]
    return story


def skeleton_story():
    story = [
        Paragraph("Alpecca Feature And Function Skeleton", TITLE),
        Paragraph("Corrected source-backed status map. Red means unsafe to activate; green requires runtime and security evidence.", SUBTITLE),
        legend_table(),
        Spacer(1, 5 * mm),
        truth_table(),
        PageBreak(),
        Paragraph("Feature Skeleton: Tiers 1-5", H1),
        feature_table(FEATURE_TIERS[:5]),
        PageBreak(),
        Paragraph("Feature Skeleton: Tiers 6-9", H1),
        feature_table(FEATURE_TIERS[5:]),
        Spacer(1, 6 * mm),
        Paragraph("Critical implementation order", H2),
        phases_table(PHASES[:5]),
    ]
    return story


def architecture_story():
    matrix = [
        ("Authoritative local core", "PARTIAL", "CoreMind, Soul, SQLite, Mindpage, affect, TTS", "Must own identity, policy, memory, approvals, and presence"),
        ("Identity/presence gateway", "BLOCKED", "Creator principal, sessions, bridge signing, singleton, portal lease", "Required before remote autonomy or multiple surfaces"),
        ("Perception/action broker", "PARTIAL", "Files, image, audio, screen, webcam, tools, pagefile", "Scoped grants and immutable approval receipts"),
        ("Cloud egress", "NOT STARTED", "Provider/data classifier for ZeroGPU, notebook, cloud models", "Deny by default; local fallback remains viable"),
        ("Mindscape", "BLOCKED", "Signed versioned snapshots and standby continuity", "Never a simultaneous clone or unapproved restore"),
        ("Embodied surfaces", "PARTIAL", "House HQ, virtual app, PWA, Discord, V4 VRM", "One writable portal; other surfaces observe or request handoff"),
    ]
    return [
        Paragraph("Alpecca Entire Project Architecture Map", TITLE),
        Paragraph("Trust boundaries, compute ownership, current status, and the dependency spine.", SUBTITLE),
        ArchitectureMap(),
        PageBreak(),
        Paragraph("Architecture Matrix", H1),
        build_table(["LAYER", "STATUS", "COMPONENTS", "OWNERSHIP RULE"], matrix,
                    [67 * mm, 32 * mm, 126 * mm, 131 * mm], status_col=1, font_size=7.5),
        Spacer(1, 7 * mm),
        Paragraph("Compute truth", H2),
        truth_table(),
        Spacer(1, 7 * mm),
        rich("<b>Superseded claim:</b> 34 GB DDR5 and H100 are not local-host specifications. They are cloud runtime annotations only when a ZeroGPU or Google notebook session actually reports them.", BODY),
        Spacer(1, 5 * mm),
        Paragraph("Dependency spine", H2),
        phases_table(PHASES[:5]),
    ]


def write_pdf(path: Path, story) -> None:
    doc = document(path)
    doc.build(story, onFirstPage=draw_page_chrome, onLaterPages=draw_page_chrome)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    master_output = OUTPUT / "ALPECCA_MASTER_PLAN.pdf"
    write_pdf(master_output, master_story())
    shutil.copy2(master_output, DOCS / "ALPECCA_MASTER_PLAN.pdf")

    write_pdf(DOCS / "ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.pdf", skeleton_story())
    write_pdf(DOCS / "ALPECCA_PROJECT_ARCHITECTURE_MAP.pdf", architecture_story())

    print(master_output)
    print(DOCS / "ALPECCA_MASTER_PLAN.pdf")
    print(DOCS / "ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.pdf")
    print(DOCS / "ALPECCA_PROJECT_ARCHITECTURE_MAP.pdf")


if __name__ == "__main__":
    main()
