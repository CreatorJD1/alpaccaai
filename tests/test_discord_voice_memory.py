from __future__ import annotations

from alpecca.discord_voice_memory import EncryptedVoiceMemoryStore


SECRET = b"voice-memory-test-secret-with-more-than-thirty-two-bytes"


def test_voice_transcript_and_identity_are_encrypted_at_rest(tmp_path):
    db_path = tmp_path / "voice-memory.db"
    store = EncryptedVoiceMemoryStore(db_path, secret=SECRET)
    transcript = "The cobalt notebook belongs beside the terminal."

    memory_id = store.remember(
        transcript,
        guild_id=100,
        channel_id=200,
        speaker_id=300,
        speaker_name="CreatorJD",
        duration_seconds=1.25,
        timestamp=1234.0,
    )

    raw = db_path.read_bytes()
    assert transcript.encode() not in raw
    assert b"CreatorJD" not in raw
    assert b"100" not in raw
    assert memory_id > 0

    memories = store.recent(guild_id=100, channel_id=200)
    assert len(memories) == 1
    memory = memories[0]
    assert memory.id == memory_id
    assert memory.timestamp == 1234.0
    assert memory.speaker_id == 300
    assert memory.speaker_name == "CreatorJD"
    assert memory.transcript == transcript
    assert memory.duration_seconds == 1.25


def test_voice_memories_are_room_isolated_and_chronological(tmp_path):
    store = EncryptedVoiceMemoryStore(tmp_path / "voice-memory.db", secret=SECRET)
    store.remember(
        "first room memory",
        guild_id=1,
        channel_id=2,
        speaker_id=3,
        speaker_name="One",
        duration_seconds=0.5,
        timestamp=10.0,
    )
    store.remember(
        "other room memory",
        guild_id=1,
        channel_id=9,
        speaker_id=4,
        speaker_name="Other",
        duration_seconds=0.5,
        timestamp=11.0,
    )
    store.remember(
        "second room memory",
        guild_id=1,
        channel_id=2,
        speaker_id=5,
        speaker_name="Two",
        duration_seconds=0.5,
        timestamp=12.0,
    )

    memories = store.recent(guild_id=1, channel_id=2)
    assert [memory.transcript for memory in memories] == [
        "first room memory",
        "second room memory",
    ]


def test_wrong_key_cannot_recover_voice_memory(tmp_path):
    db_path = tmp_path / "voice-memory.db"
    writer = EncryptedVoiceMemoryStore(db_path, secret=SECRET)
    writer.remember(
        "private spoken memory",
        guild_id=1,
        channel_id=2,
        speaker_id=3,
        speaker_name="Speaker",
        duration_seconds=0.5,
    )

    reader = EncryptedVoiceMemoryStore(
        db_path,
        secret=b"different-secret-material-that-is-also-long-enough",
    )
    assert reader.recent(guild_id=1, channel_id=2) == []


def test_voice_memory_store_prunes_to_configured_bound(tmp_path):
    store = EncryptedVoiceMemoryStore(
        tmp_path / "voice-memory.db",
        secret=SECRET,
        max_records=32,
    )
    for index in range(40):
        store.remember(
            f"bounded memory {index}",
            guild_id=1,
            channel_id=2,
            speaker_id=3,
            speaker_name="Speaker",
            duration_seconds=0.5,
            timestamp=float(index + 1),
        )

    assert store.status()["records"] == 32
    assert [memory.transcript for memory in store.recent(
        guild_id=1,
        channel_id=2,
        limit=24,
    )] == [f"bounded memory {index}" for index in range(16, 40)]
