"""Build the current Alpecca architecture, feature skeleton, and master-plan PDFs.

The PDFs are generated from the same reviewed status model so their colors and
claims cannot drift independently. The script intentionally contains no secrets,
live credentials, or private contact destinations.
"""

from __future__ import annotations

import html
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
    canvas.drawString(16 * mm, 9 * mm, "Source-reviewed 2026-07-15 | local-first | one authoritative CoreMind")
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
            (20, 175, "DISCORD / VOICE", "Claimed rooms, media, bounded voice send/receive; live duplex soak pending", "PARTIAL"),
            (20, 80, "CREATOR CONTACT", "Model-free Web Push connection test; enrollment and mobile soak pending", "PARTIAL"),
        ]
        outputs = [
            (825, 365, "LOCAL PERCEPTION", "Files, image, audio, screen, webcam with scoped grants", "PARTIAL"),
            (825, 270, "ACTION BROKER", "Tools, computer use, OS/pagefile, immutable approvals", "BLOCKED"),
            (825, 175, "CLOUD EGRESS", "Deny-by-default consent ledger exists; production adapter is unwired", "PARTIAL"),
            (825, 80, "MINDSCAPE", "Encrypted passive Vault and inert standby; promotion remains blocked", "BLOCKED"),
        ]
        for x, y, title, detail, state in surfaces:
            self._node(c, x, y, 180, 76, title, detail, state)
        for x, y, title, detail, state in outputs:
            self._node(c, x, y, 210, 76, title, detail, state)

        self._node(c, 245, 125, 185, 270, "IDENTITY + PRESENCE GATE", "Creator principal; scoped sessions; OS singleton; portal epoch fencing; signed bridge envelopes; privacy scope", "PARTIAL")
        self._node(c, 485, 125, 285, 270, "AUTHORITATIVE LOCAL COREMIND", "Turn transaction -> cues -> retrieve -> Soul -> affect -> intent -> tools/response -> commitment receipt -> evaluate. SQLite and Mindpage remain local authority.", "PARTIAL")

        for _, y, *_ in surfaces:
            self._arrow(c, 200, y + 38, 245, 260)
        self._arrow(c, 430, 260, 485, 260, "scoped turn")
        for _, y, *_ in outputs:
            self._arrow(c, 770, 260, 825, y + 38)

        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20, 30, "COMPUTE / STORAGE OWNERSHIP")
        self._node(c, 230, 5, 250, 56, "LOCAL LAPTOP - AUTHORITATIVE", "Approx. 24 GB DDR4 + RTX 3050 4 GB; policy, memory, identity, approvals", "PARTIAL")
        self._node(c, 500, 5, 240, 56, "HF ZEROGPU - EPHEMERAL", "Stateless bounded inference; assigned hardware and quota are runtime-probed", "PARTIAL")
        self._node(c, 760, 5, 260, 56, "GOOGLE NOTEBOOK - EPHEMERAL", "Stateless bounded jobs; GPU/RAM/uptime are not guaranteed", "PARTIAL")
        c.restoreState()


FEATURE_TIERS = [
    ("Tier 1 - Foundation runtime", [
        ("FastAPI, WebSocket, runtime status", "PARTIAL", "Protected runtime works; final clean-shell publication evidence remains open"),
        ("Ollama routing and offline fallback", "PARTIAL", "Configured qwen3.5:9b local path works; production cloud egress remains unwired"),
        ("SQLite state, memory, journal, proposals", "PARTIAL", "Functional with verified local snapshots; transactional cloud promotion remains blocked"),
        ("Remote auth and tunnels", "PARTIAL", "Trusted-device HTTPS auth works; the current relay is temporary and discoverable"),
        ("Singleton and active portal", "DONE", "Cross-process singleton ownership and stale portal fencing are tested"),
    ]),
    ("Tier 2 - Cognition and agency", [
        ("Soul seven-perspective arbitration", "DONE", "One deterministic seven-score vector feeds one arbitration path with zero model calls"),
        ("Scoped CoreMind turn transaction", "DONE", "Scoped immutable turns, cancellation barriers, and stale-commit rejection are tested"),
        ("Constrained choice points", "DONE", "Living, Soul tie-break, and proactive judge with fallback"),
        ("Tool registry and planner", "PARTIAL", "Creator and guest capabilities are constrained; the broader action broker remains gated"),
        ("Bounded self_status commitment ledger", "DONE", "Bounded self_status execution is creator-only, exactly-once, and receipt-backed"),
    ]),
    ("Tier 3 - Memory and Mindpage", [
        ("Keyword/FTS recall and backfill", "PARTIAL", "Bounded recall works; the full resource and long-context promotion gate remains open"),
        ("Mindpage Layer A", "PARTIAL", "Paging, pressure sensing, and safe preflight exist; real 8,192-context proof is absent"),
        ("Conversation/privacy partitioning", "DONE", "Actor, surface, conversation, and privacy scope are transaction-bound and tested"),
        ("Resource pressure sensing", "PARTIAL", "Pressure sensing and safe preflight exist; successful real promotion is unverified"),
        ("Approved pagefile broker", "BLOCKED", "Read-only exact-step planning exists; no UAC helper or system mutation exists"),
        ("llama.cpp KV persistence", "PARKED", "Downloaded experiment; not integrated"),
    ]),
    ("Tier 4 - Autonomy and improvement", [
        ("Proactive/living behavior", "DONE", "Shared per-scope initiative budget, dedupe, one-surface delivery, and backoff are tested"),
        ("Recursive self-improvement", "PARTIAL", "Bounded trial lifecycle and rollback are green; no creator-approved live trial has soaked"),
        ("External action approval", "PARTIAL", "Bounded self_status closure works; privileged and general action approval remains gated"),
        ("Bounded self_status receipts", "DONE", "The bounded commitment path closes exactly once with durable evidence"),
    ]),
    ("Tier 5 - Automation", [
        ("Bounded routines and initiative budget", "DONE", "Routine, proactive, and living paths share one initiative budget and dedupe policy"),
        ("Background job coordination", "PARTIAL", "Timeouts do not cancel worker threads"),
        ("MCP federation", "PARKED", "Deferred external surface"),
    ]),
    ("Tier 6 - Experience and embodiment", [
        ("House HQ and virtual app", "PARTIAL", "Working surfaces with fenced ownership; live phone acceptance and restart proof remain"),
        ("V4 VRM body and physics", "PARTIAL", "VRM 1.0 with 74 spring joints; live walk and ten-minute physics proof remain"),
        ("Expression and gesture control", "PARTIAL", "Unsafe repeated VRMA seams and latched gaze are fixed; live visual proof remains"),
        ("Locked design QA", "PARTIAL", "The locked V4 is retained; authenticated design and motion proof remains open"),
    ]),
    ("Tier 7 - Voice, senses, and communication", [
        ("Local TTS voice", "PARTIAL", "Local speech and Discord send paths work; live acoustic acceptance remains open"),
        ("Image and file perception", "PARTIAL", "Bounded local ingress and provenance work; production egress remains unwired"),
        ("Audio perception", "PARTIAL", "Bounded local Discord receive/transcription exists; live packet and latency soak is pending"),
        ("Discord autonomy", "PARTIAL", "Claimed rooms, guest authority, cooldowns, and bounded deliberation exist; live soak remains"),
        ("Creator contact outbox", "PARTIAL", "Model-free durable Web Push connection test exists; enrollment and mobile soak remain"),
        ("Computer use", "BLOCKED", "Privileged general computer control is not release-promoted or autonomously available"),
    ]),
    ("Tier 8 - Cloud and continuity", [
        ("Hugging Face art/runtime assets", "PARTIAL", "Correct storage lane; publish/availability remain operational"),
        ("ZeroGPU / Google notebook", "PARTIAL", "Optional ephemeral adapters; no production consented route is live"),
        ("Cloudflare R2 lanes", "PARTIAL", "Credential-free discovery and encrypted Vault storage work; fixed ingress remains gated"),
        ("Mindscape continuity", "BLOCKED", "Encrypted passive Vault and inert standby exist; promotion and failover remain absent"),
        ("Cloud egress broker", "PARTIAL", "A deny-by-default exact-operation ledger exists; production adapters remain unwired"),
    ]),
    ("Tier 9 - Governance", [
        ("Design lock and canonical docs", "DONE", "Current hierarchy and locked character design exist"),
        ("Creator identity and secret lifecycle", "PARTIAL", "Creator identity is tested and secret scan is clean; final publication receipt remains"),
        ("Grounded affect/self-report", "DONE", "Evidence-backed engineered state is reported without literal-consciousness claims"),
        ("Only pagefile as planned OS mutation", "PARTIAL", "Policy exists; broker is not safe or active"),
    ]),
]


PHASES = [
    ("0", "Truth baseline and freeze", "DONE", "Canonical status, local/cloud ownership, bounded claims, and encrypted recovery baseline are established.", "Current diagrams follow evidence; ephemeral cloud capacity is never counted as local."),
    ("1", "Security containment", "PARTIAL", "Protected HTTP/WS auth, capability audits, device trust, and a zero-finding source plus House secret scan exist.", "Retain a final clean-shell publication receipt without exposing credentials."),
    ("2", "Creator identity, singleton, portal lease", "DONE", "Stable creator identity, cross-process singleton ownership, and stale portal fencing are tested.", "One supported CoreMind and writer; spoofed creator claims and stale portals fail."),
    ("3", "Turn transactions and context isolation", "DONE", "Immutable scoped turns, cancellation barriers, and stale-commit rejection are tested.", "No cross-actor leak; timed-out work creates no late effects."),
    ("4", "Cue, commitment, action closure", "DONE", "The bounded creator-only self_status path is exactly-once and receipt-backed.", "Completion language follows durable execution evidence."),
    ("5", "Initiative and grounded affect", "DONE", "One per-scope initiative budget governs routines, living ticks, and proactive speech with dedupe and backoff.", "No duplicate outreach; ignored contact backs off; affect remains grounded."),
    ("6", "Mindpage and resource coordinator", "PARTIAL", "Paging, pressure sensing, and safe preflight exist.", "Promote only after a successful real 8,192-context measurement."),
    ("7", "Approved pagefile broker", "BLOCKED", "Read-only exact-step planning exists; no UAC helper, write, or system mutation exists.", "Durable one-use approval, live recheck, privileged helper, and readback must all pass."),
    ("8", "Bounded recursive improvement", "PARTIAL", "Two-hour/five-outcome trial lifecycle, rollback, and creator retention decision are test-green.", "A real creator-approved trial must soak; no autonomous source, shell, account, or OS edits."),
    ("9", "Multimodal and source perception", "PARTIAL", "Bounded local source/image/audio ingress, leases, provenance, and an unwired consent ledger exist.", "Wire one attested production egress route without exposing private payloads."),
    ("10", "Discord presence and voice", "PARTIAL", "Claimed rooms, signed guest actors, media, voice send, and bounded local receive foundations exist.", "Complete a real duplex packet, latency, and voice-quality soak plus production anchor."),
    ("11", "Creator contact outbox", "PARTIAL", "A durable model-free Web Push connection-test path exists.", "Complete browser enrollment, provider acceptance, one-use click acknowledgement, and mobile soak."),
    ("12", "V4 embodiment behavior", "PARTIAL", "V4 is VRM 1.0 with 74 spring joints; gait, seam, and gaze fixes are implemented.", "Complete authenticated walk, terminal-contact, design, and ten-minute physics proof."),
    ("13", "Cloud continuity", "BLOCKED", "Encrypted passive Vault, inert Ubuntu standby, fenced lease, and one-use restore approval exist.", "Transactional promotion and an actual provider VM remain required; never run a second CoreMind."),
    ("14", "Release soak and living docs", "BLOCKED", "Observation-only soak and public mobile probes plus content-free secret-scan evidence exist.", "Full live soak windows, resource/Discord/V4/continuity evidence, and clean deployment proof remain."),
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
            ("Local laptop", "Authoritative CoreMind, state, policy, identity, approvals, live fallback", "Approximately 24 GB DDR4; RTX 3050 Laptop GPU with 4 GB VRAM"),
            ("Hugging Face ZeroGPU", "Optional stateless deep/vision/texture/batch inference", "Ephemeral, quota-governed, runtime-probed; never counted as local capacity"),
            ("Google notebook / Colab", "Optional stateless accelerated inference or batch jobs", "Ephemeral; GPU, RAM, uptime, and limits are not guaranteed"),
        ],
        [55 * mm, 145 * mm, 156 * mm],
    )


def pagefile_table():
    return build_table(
        ["POLICY POINT", "PAGEFILE MAX", "C: FREE EVIDENCE", "DECISION"],
        [
            ("Historical observation", "38,000 MiB", "57.91 GiB at prior audit", "Not current authorization; all telemetry must be reread"),
            ("Example step 1", "42,096 MiB", "Must project >= 40 GiB", "Eligible only after pressure proof and fresh approval"),
            ("Example step 2", "46,192 MiB", "Must project >= 40 GiB", "Requires a separate later approval"),
            ("Example step 3", "50,288 MiB", "Must project >= 40 GiB", "Requires a separate later approval"),
            ("Example step 4", "54,384 MiB", "Must project >= 40 GiB", "Highest exact 4 GiB example below the hard cap"),
            ("Rejected example", "58,480 MiB", "Would violate policy", "Rejected by 55,296 MiB cap"),
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
            "<b>Compute boundary:</b> the laptop is approximately 24 GB DDR4 with an RTX 3050 Laptop GPU (4 GB). "
            "Optional ZeroGPU or Google notebook memory and accelerator details are ephemeral runtime observations. "
            "They are never Alpecca's local hardware or guaranteed capacity.",
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

    open_gates = [
        ("1", "P1 publication receipt", "Protected HTTP/WS auth, device trust, capability audits, and a zero-finding source plus House scan exist.", "Retain a final clean-shell publication receipt without credentials."),
        ("2", "P6 resource promotion", "Mindpage paging, pressure sensing, and safe preflight are implemented.", "Complete one successful real 8,192-context measurement before promotion."),
        ("3", "P7 pagefile broker", "Read-only exact-step planning exists; no UAC helper, write, or system mutation exists.", "Finish durable approval, fresh telemetry recheck, privileged helper, and readback."),
        ("4", "P10/P11 live communication", "Discord duplex foundations and a model-free Web Push test path are implemented.", "Run creator voice quality and mobile provider/acknowledgement soaks."),
        ("5", "P12 embodiment proof", "V4 gait restart, displacement yaw, unsafe seams, and gaze reset are fixed.", "Capture authenticated walking, terminal contact, design, and ten-minute physics evidence."),
        ("6", "P13/P14 release evidence", "Passive Vault, inert standby, observation-only soak, mobile probes, and secret scan exist.", "Prove transactional continuity and complete all live release-soak windows."),
    ]
    story += [PageBreak(), Paragraph("Open Gates And Safe Next Actions", H1), build_table(
        ["#", "OPEN GATE", "CURRENT EVIDENCE", "SAFE NEXT PROOF"], open_gates,
        [12 * mm, 68 * mm, 141 * mm, 135 * mm], font_size=7.6),
        Spacer(1, 7 * mm), Paragraph("Non-negotiable autonomy boundary", H2),
        p("One CoreMind and one writable portal. Webcam, screen, files, microphone, Discord, and computer use require visible, revocable session grants. No autonomous source edits, account actions, deletes, purchases, or general OS changes. The only planned OS mutation is one exact pagefile step after fresh CreatorJD approval and UAC; that broker remains blocked and inert."),
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
            ("Creator identity", "DONE", "Server-derived creator principal, paired devices, scoped sessions, and signed bridge envelopes", "Request bodies cannot claim creator authority; spoofing and stale sessions fail"),
            ("Active portal", "DONE", "Cross-process singleton ownership plus surface/session/epoch fencing", "Simultaneous claims have one winner; stale portals cannot write"),
            ("Discord", "PARTIAL", "Allowlisted DMs and claimed rooms, signed guests, scoped history, cooldowns, and bounded speech", "Complete live duplex soak and independent production actor anchor"),
            ("Voice", "PARTIAL", "Opt-in local send and separately gated bounded creator-only receive/transcription", "Measure packet/latency and voice quality; discard raw audio after the turn"),
            ("Creator contact", "PARTIAL", "Durable model-free Web Push connection test with separate provider and acknowledgement states", "Complete enrollment, provider acceptance, one-use click acknowledgement, and mobile soak"),
            ("Mindscape", "BLOCKED", "Encrypted passive Vault, preview, digest-bound restore approval, and inert fenced standby", "Transactional promotion and an actual provider VM; never a second live CoreMind"),
        ], [54 * mm, 31 * mm, 145 * mm, 126 * mm], status_col=1, font_size=7.15),
        Spacer(1, 6 * mm), p("Local/cloud boundary: Discord connectivity, identity, approvals, rate limits, memory, STT/TTS, posting, and presence stay local. Ephemeral cloud compute may return stateless text/vision results only after provider-specific data policy approval."),
    ]

    story += [PageBreak(), Paragraph("V4 Embodiment Promotion Plan", H1),
        rich("<b>Current verified body:</b> V4 remains VRM 1.0 with the locked design and 74 spring joints. Implemented fixes are evidence, not a substitute for the still-open authenticated visual soak.", BODY),
        build_table(["AREA", "CURRENT EVIDENCE", "REMAINING WORK", "PROMOTION GATE"], [
            ("Grounding", "Transformed raw-skeleton heel/toe contacts drive collision-resolved grounding", "Inspect the full authenticated walk and terminal contact", "No visible float, penetration, or planted-foot instability"),
            ("Locomotion", "Walking resets at lift-off, follows actual movement, and uses displacement-derived yaw", "Exercise starts, stops, reroutes, and blocked movement live", "Motion follows displacement without sliding or stale gait state"),
            ("Expressions and gaze", "Latched gaze reset is fixed and speech timing follows actual playback", "Run authenticated face, blink, gaze, and speech transitions", "Return to a stable neutral state without stuck expression or gaze"),
            ("VRMA seams", "Unsafe repeated clip seams are rejected", "Exercise all allowed one-shot and repeated animation transitions", "No snap, loop seam, or unexplained idle flourish"),
            ("Physics", "V4 retains 74 spring joints and collision-aware walking fixes", "Run the required ten-minute live physics soak", "No NaN, runaway spring motion, or terminal contact regression"),
            ("Design lock", "The locked V4 design and topology are retained", "Capture fixed-view authenticated design evidence", "Current locked design passes without regeneration or topology drift"),
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
        ("Identity/presence gateway", "DONE", "Creator principal, sessions, bridge signing, singleton, portal fencing", "Cross-process ownership and stale portal rejection are tested"),
        ("Perception/action broker", "PARTIAL", "Files, image, audio, screen, webcam, tools, pagefile", "Scoped grants and immutable approval receipts"),
        ("Cloud egress", "PARTIAL", "Exact-operation consent ledger for provider, deployment, model, and payload", "Production adapters remain unwired; deny by default"),
        ("Mindscape", "BLOCKED", "Encrypted passive Vault, approved restore path, inert fenced standby", "No transactional promotion, provider VM, or simultaneous clone"),
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
        rich("<b>Compute boundary:</b> cloud-reported RAM and accelerator details are ephemeral runtime facts. They are never local-host specifications or guaranteed capacity.", BODY),
        Spacer(1, 5 * mm),
        Paragraph("Dependency spine", H2),
        phases_table(PHASES[:5]),
    ]


def write_pdf(path: Path, story) -> None:
    doc = document(path)
    doc.build(story, onFirstPage=draw_page_chrome, onLaterPages=draw_page_chrome)


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)

    write_pdf(DOCS / "ALPECCA_MASTER_PLAN.pdf", master_story())
    write_pdf(DOCS / "ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.pdf", skeleton_story())
    write_pdf(DOCS / "ALPECCA_PROJECT_ARCHITECTURE_MAP.pdf", architecture_story())

    print(DOCS / "ALPECCA_MASTER_PLAN.pdf")
    print(DOCS / "ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.pdf")
    print(DOCS / "ALPECCA_PROJECT_ARCHITECTURE_MAP.pdf")


if __name__ == "__main__":
    main()
