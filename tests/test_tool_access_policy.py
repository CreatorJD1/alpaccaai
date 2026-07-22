from alpecca import tool_access_policy


def test_self_affecting_tools_require_creator():
    policy = tool_access_policy.classify("journal_write")
    assert policy["category"] == "self_affecting"
    assert policy["creator_required"] is True
    assert policy["approval_required"] is False


def test_external_effect_is_not_creator_identity_by_definition():
    policy = tool_access_policy.classify("open_url")
    assert policy["category"] == "external_effect"
    assert policy["creator_required"] is False
    assert policy["approval_required"] is False

    controlled = tool_access_policy.classify("computer_use")
    assert controlled["approval_required"] is True


def test_nonprivate_results_can_use_chat_or_private_drive_links():
    policy = tool_access_policy.classify("public_document_lookup")
    assert policy["creator_required"] is False
    assert "chat_html" in policy["shareable_result_channels"]
    assert "google_drive_private" in policy["shareable_result_channels"]
    assert tool_access_policy.result_may_be_shared(
        "public_document_lookup", contains_private_data=False,
    ) is True
    assert tool_access_policy.result_may_be_shared(
        "memory_search", contains_private_data=False,
    ) is False
