import base64
import json
import os
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from skillbook.domain import Release, canonical, digest

MAX_BUNDLE = 2 * 1024 * 1024


def read_bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_BUNDLE + 1)
    if len(data) > MAX_BUNDLE:
        raise ValueError("Release exceeds 2 MiB")
    return data


def sign(release: Release, key: Ed25519PrivateKey) -> bytes:
    payload = release.model_dump()
    signature = base64.b64encode(key.sign(canonical(payload))).decode()
    return canonical({"payload": payload, "signature": signature})


def public_key(path: Path) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(read_bounded(path))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("An Ed25519 public key is required")
    return key


def verify(data: bytes, key: Ed25519PublicKey) -> Release:
    if len(data) > MAX_BUNDLE:
        raise ValueError("Release exceeds 2 MiB")
    try:
        envelope = json.loads(data)
        if set(envelope) != {"payload", "signature"}:
            raise ValueError("Invalid release envelope")
        signature = base64.b64decode(envelope["signature"], validate=True)
        key.verify(signature, canonical(envelope["payload"]))
        return Release.model_validate(envelope["payload"])
    except (InvalidSignature, KeyError, TypeError) as exc:
        raise ValueError("Untrusted or malformed release") from exc


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class ReleaseStore:
    """Operator-owned state. Mutations require an exclusive filesystem lock on Unix."""

    def __init__(self, directory: Path, key: Ed25519PublicKey):
        self.directory, self.key = directory, key

    def state(self) -> dict:
        path = self.directory / "active.json"
        return json.loads(read_bounded(path)) if path.exists() else {"highest": 0, "active": None}

    def load(self) -> Release:
        state = self.state()
        active = state["active"]
        if (
            not isinstance(active, str)
            or len(active) != 64
            or any(char not in "0123456789abcdef" for char in active)
        ):
            raise ValueError("No valid active release")
        data = read_bounded(self.directory / "releases" / f"{active}.json")
        if digest(data) != active:
            raise ValueError("Installed bundle modified")
        return verify(data, self.key)

    def activate(self, data: bytes) -> dict:
        import fcntl

        release = verify(data, self.key)
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self.state()
            if release.version <= state["highest"]:
                raise ValueError(
                    "Replay/downgrade rejected; use explicit rollback for installed data"
                )
            identifier = digest(data)
            atomic_write(self.directory / "releases" / f"{identifier}.json", data)
            state = {"highest": release.version, "active": identifier}
            atomic_write(self.directory / "active.json", canonical(state))
            return state

    def rollback(self, identifier: str) -> dict:
        import fcntl

        if len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
            raise ValueError("Invalid installed release identifier")
        with (self.directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = read_bounded(self.directory / "releases" / f"{identifier}.json")
            if digest(data) != identifier:
                raise ValueError("Installed bundle modified")
            release = verify(data, self.key)
            state = self.state()
            if release.version > state["highest"]:
                raise ValueError("Rollback target was not activated")
            state["active"] = identifier
            atomic_write(self.directory / "active.json", canonical(state))
            return state
