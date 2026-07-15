import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from alpecca.trusted_devices import DeviceAuthError, TrustedDeviceRegistry


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _keypair():
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, _b64(public)


def test_enroll_challenge_exchange_is_single_use_and_origin_bound(tmp_path):
    clock = [1000.0]
    registry = TrustedDeviceRegistry(tmp_path / "devices.db", now=lambda: clock[0])
    private, public = _keypair()
    device = registry.enroll(public)
    challenge = registry.issue_challenge(device["device_id"], "https://one.example")
    message = base64.urlsafe_b64decode(challenge["message"] + "==")
    lines = message.decode("utf-8").split("\n")
    assert lines == [
        "alpecca-device-auth-v2",
        device["device_id"],
        challenge["challenge_id"],
        str(challenge["expires_at"]),
        lines[4],
        "https://one.example",
    ]
    assert len(base64.urlsafe_b64decode(lines[4] + "=")) == 32
    signature = _b64(private.sign(message, ec.ECDSA(hashes.SHA256())))

    with pytest.raises(DeviceAuthError, match="challenge_rejected"):
        registry.exchange(challenge["challenge_id"], signature, "https://two.example")
    assert registry.exchange(challenge["challenge_id"], signature, "https://one.example") == device["device_id"]
    with pytest.raises(DeviceAuthError, match="challenge_expired"):
        registry.exchange(challenge["challenge_id"], signature, "https://one.example")


def test_expiry_revocation_and_invalid_signature_fail_closed(tmp_path):
    clock = [2000.0]
    registry = TrustedDeviceRegistry(tmp_path / "devices.db", now=lambda: clock[0])
    private, public = _keypair()
    other, _ = _keypair()
    device = registry.enroll(public)
    challenge = registry.issue_challenge(device["device_id"], "https://phone.example")
    message = base64.urlsafe_b64decode(challenge["message"] + "==")
    bad_signature = _b64(other.sign(message, ec.ECDSA(hashes.SHA256())))
    with pytest.raises(DeviceAuthError, match="signature_invalid"):
        registry.exchange(challenge["challenge_id"], bad_signature, "https://phone.example")

    clock[0] += 121
    signature = _b64(private.sign(message, ec.ECDSA(hashes.SHA256())))
    with pytest.raises(DeviceAuthError, match="challenge_expired"):
        registry.exchange(challenge["challenge_id"], signature, "https://phone.example")
    assert registry.revoke(device["device_id"])
    assert registry.active_count() == 0
    with pytest.raises(DeviceAuthError, match="device_unknown"):
        registry.issue_challenge(device["device_id"], "https://phone.example")


def test_duplicate_public_key_reuses_active_registration(tmp_path):
    registry = TrustedDeviceRegistry(tmp_path / "devices.db")
    _, public = _keypair()
    first = registry.enroll(public, label="Jason phone")
    second = registry.enroll(public, label="CreatorJD phone")
    assert first["device_id"] == second["device_id"]
    assert registry.active_count() == 1


def test_revoked_key_cannot_silently_reenroll_and_sessions_stop(tmp_path):
    clock = [3000.0]
    registry = TrustedDeviceRegistry(tmp_path / "devices.db", now=lambda: clock[0])
    _, public = _keypair()
    device = registry.enroll(public)
    assert registry.session_valid(device["device_id"], 3000)
    assert registry.revoke(device["device_id"])
    assert not registry.session_valid(device["device_id"], 3000)
    with pytest.raises(DeviceAuthError, match="device_revoked"):
        registry.enroll(public)


def test_device_bound_session_payload_is_explicit_and_origin_bound():
    from alpecca.auth import SessionAuthority

    authority = SessionAuthority("test-secret", session_ttl_s=60)
    cookie = authority.issue_session_cookie(
        secure=True,
        now=1000,
        device_id="device-id-12345",
        origin="https://phone.example",
    )
    decision = authority.validate_session_cookie(cookie.value, now=1000)
    assert decision.allowed
    assert decision.device_id == "device-id-12345"
    assert decision.session_origin == "https://phone.example"
    with pytest.raises(ValueError, match="both"):
        authority.issue_session_cookie(device_id="device-id-12345")


def test_server_device_exchange_mints_http_only_cookie(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import server

    registry = TrustedDeviceRegistry(tmp_path / "server-devices.db")
    monkeypatch.setattr(server, "_TRUSTED_DEVICE_REGISTRY", registry)
    private, public = _keypair()
    session = server._AUTHORITY.issue_session_cookie(secure=True)
    client = TestClient(server.app, base_url="https://testserver")
    client.cookies.set(session.name, session.value)
    headers = {"Origin": "https://testserver"}

    enrolled = client.post(
        "/auth/device/enroll",
        headers=headers,
        json={"label": "test phone", "public_key": public},
    )
    assert enrolled.status_code == 200
    device_id = enrolled.json()["device_id"]

    client.cookies.clear()
    challenge = client.post(
        "/auth/device/challenge",
        headers=headers,
        json={"device_id": device_id},
    )
    assert challenge.status_code == 200
    payload = challenge.json()
    message = base64.urlsafe_b64decode(payload["message"] + "==")
    signature = _b64(private.sign(message, ec.ECDSA(hashes.SHA256())))
    exchanged = client.post(
        "/auth/device/exchange",
        headers=headers,
        json={"challenge_id": payload["challenge_id"], "signature": signature},
    )
    assert exchanged.status_code == 200
    assert "alpecca_authorization=" in exchanged.headers["set-cookie"]
    assert "HttpOnly" in exchanged.headers["set-cookie"]
    assert "SameSite=strict" in exchanged.headers["set-cookie"]

    protected = client.get("/security/capabilities", headers={"Accept": "application/json"})
    assert protected.status_code == 200

    revoked = client.delete(f"/auth/device/{device_id}", headers=headers)
    assert revoked.status_code == 200
    assert registry.active_count() == 0
    rejected = client.get("/security/capabilities", headers={"Accept": "application/json"})
    assert rejected.status_code == 401

    replay = client.post(
        "/auth/device/exchange",
        headers=headers,
        json={"challenge_id": payload["challenge_id"], "signature": signature},
    )
    assert replay.status_code == 401


def test_server_device_challenge_rejects_cross_origin(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import server

    registry = TrustedDeviceRegistry(tmp_path / "server-devices.db")
    monkeypatch.setattr(server, "_TRUSTED_DEVICE_REGISTRY", registry)
    _, public = _keypair()
    device = registry.enroll(public)
    client = TestClient(server.app, base_url="https://testserver")
    response = client.post(
        "/auth/device/challenge",
        headers={"Origin": "https://attacker.example"},
        json={"device_id": device["device_id"]},
    )
    assert response.status_code == 403


def test_server_rejects_device_cookie_on_a_different_origin(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import server

    registry = TrustedDeviceRegistry(tmp_path / "server-devices.db", now=lambda: 1000)
    monkeypatch.setattr(server, "_TRUSTED_DEVICE_REGISTRY", registry)
    _, public = _keypair()
    device = registry.enroll(public)
    cookie = server._AUTHORITY.issue_session_cookie(
        secure=True,
        device_id=device["device_id"],
        origin="https://one.example",
    )
    client = TestClient(server.app, base_url="https://two.example")
    client.cookies.set(cookie.name, cookie.value)
    response = client.get("/security/capabilities", headers={"Accept": "application/json"})
    assert response.status_code == 401
