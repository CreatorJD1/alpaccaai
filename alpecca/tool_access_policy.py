"""Effect-based access classification for Alpecca tools and their results."""
from __future__ import annotations


SELF_AFFECTING = frozenset({
    "journal_write", "note_to_self", "go_to_room", "make_plan",
    "execute_approved_step", "pagefile_resize", "self_modify",
})

PRIVATE_READ = frozenset({
    "memory_search", "journal_read", "self_status", "source_inspect",
    "recall_page", "find_file", "screen_read", "camera_read", "google_status",
})

CREATOR_EXTERNAL_EFFECT = frozenset({
    "google_create_folder", "google_create_document",
})

EXTERNAL_EFFECT = frozenset({
    "open_app", "open_url", "computer_use", "send_message", "upload_file",
})

APPROVAL_REQUIRED = frozenset({
    "execute_approved_step", "pagefile_resize", "self_modify",
    "computer_use", "send_message", "upload_file",
})

SHAREABLE_RESULT_CHANNELS = frozenset({
    "chat_https", "chat_html", "google_drive_private",
})


def classify(tool_name: str) -> dict:
    name = str(tool_name or "").strip().lower()
    if name in SELF_AFFECTING:
        category = "self_affecting"
        creator_required = True
    elif name in PRIVATE_READ:
        category = "private_read"
        creator_required = True
    elif name in CREATOR_EXTERNAL_EFFECT:
        category = "external_effect"
        creator_required = True
    elif name in EXTERNAL_EFFECT:
        category = "external_effect"
        creator_required = False
    else:
        category = "conversation_output"
        creator_required = False
    approval_required = name in APPROVAL_REQUIRED
    return {
        "tool": name,
        "category": category,
        "creator_required": creator_required,
        "approval_required": approval_required,
        "shareable_result_channels": sorted(SHAREABLE_RESULT_CHANNELS),
    }


def result_may_be_shared(tool_name: str, *, contains_private_data: bool) -> bool:
    """Sharing is a separate decision from executing the underlying tool."""
    policy = classify(tool_name)
    if contains_private_data or policy["category"] == "private_read":
        return False
    return True
