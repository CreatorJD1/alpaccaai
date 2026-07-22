from alpecca import discord_creator_identity


def test_resolved_creator_id_round_trips_from_private_binding(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPECCA_DISCORD_CREATOR_ID", raising=False)
    monkeypatch.delenv("ALPECCA_DISCORD_DM_ALLOW", raising=False)

    discord_creator_identity.remember_creator_actor_id("123456789", tmp_path)

    assert discord_creator_identity.is_creator_actor_id("123456789", tmp_path)
    assert not discord_creator_identity.is_creator_actor_id("987654321", tmp_path)
    assert discord_creator_identity.binding_path(tmp_path).read_text().strip() == "123456789"


def test_username_allowlist_does_not_become_an_actor_id(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPECCA_DISCORD_DM_ALLOW", "realcreatorjd")

    assert discord_creator_identity.configured_creator_actor_ids(tmp_path) == ()
