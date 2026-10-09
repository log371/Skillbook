import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from skillbook.app import demo_release
from skillbook.releases import MAX_BUNDLE, ReleaseStore, read_bounded, sign, verify


def test_signature_tampering_and_wrong_key():
    key = Ed25519PrivateKey.generate()
    data = sign(demo_release(), key)
    assert verify(data, key.public_key()).version == 1
    with pytest.raises(ValueError):
        verify(data, Ed25519PrivateKey.generate().public_key())
    edited = json.loads(data)
    edited["payload"]["skills"]["maintenance"]["document_ids"].append("restricted")
    with pytest.raises(ValueError):
        verify(json.dumps(edited).encode(), key.public_key())


def test_activate_replay_rollback_and_reverify(tmp_path):
    key = Ed25519PrivateKey.generate()
    store = ReleaseStore(tmp_path, key.public_key())
    one = sign(demo_release(), key)
    state1 = store.activate(one)
    assert store.load().version == 1
    with pytest.raises(ValueError, match="Replay"):
        store.activate(one)
    two = sign(demo_release().model_copy(update={"version": 2}), key)
    state2 = store.activate(two)
    assert store.load().version == 2
    assert store.rollback(state1["active"])["highest"] == 2
    assert store.load().version == 1
    with pytest.raises(ValueError, match="Replay"):
        store.activate(two)
    installed = tmp_path / "releases" / (state2["active"] + ".json")
    installed.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="modified"):
        store.rollback(state2["active"])


def test_failed_update_leaves_active_release(tmp_path):
    key = Ed25519PrivateKey.generate()
    store = ReleaseStore(tmp_path, key.public_key())
    store.activate(sign(demo_release(), key))
    with pytest.raises(ValueError):
        store.activate(b"bad bundle")
    assert store.load().version == 1
    with pytest.raises(ValueError):
        store.rollback("../../escape")


def test_concurrent_activation_has_one_winner(tmp_path):
    key = Ed25519PrivateKey.generate()
    store = ReleaseStore(tmp_path, key.public_key())
    bundle = sign(demo_release(), key)

    def activate():
        try:
            store.activate(bundle)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(lambda _: activate(), range(4))) == 1
    assert store.load().version == 1


def test_oversize_and_missing_state(tmp_path):
    key = Ed25519PrivateKey.generate().public_key()
    with pytest.raises(ValueError, match="2 MiB"):
        verify(b"x" * (MAX_BUNDLE + 1), key)
    oversized = tmp_path / "large.json"
    oversized.write_bytes(b"x" * (MAX_BUNDLE + 1))
    with pytest.raises(ValueError, match="2 MiB"):
        read_bounded(oversized)
    with pytest.raises(ValueError):
        ReleaseStore(tmp_path, key).load()
