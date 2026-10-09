import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from skillbook.app import demo_release
from skillbook.audit import Audit
from skillbook.config import Settings
from skillbook.domain import Release, digest
from skillbook.evaluation import evaluate_model, evaluate_policy
from skillbook.inventory import inventory
from skillbook.releases import ReleaseStore, public_key, read_bounded, sign, verify


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def demo() -> dict:
    with tempfile.TemporaryDirectory(prefix="skillbook-demo-") as tmp:
        root = Path(tmp)
        key = Ed25519PrivateKey.generate()
        store = ReleaseStore(root / "releases", key.public_key())
        first = sign(demo_release(), key)
        state1 = store.activate(first)
        second_release = demo_release().model_copy(update={"version": 2})
        state2 = store.activate(sign(second_release, key))
        store.rollback(state1["active"])
        tampered = json.loads(first)
        tampered["payload"]["version"] = 999
        try:
            verify(json.dumps(tampered).encode(), key.public_key())
            rejected = False
        except ValueError:
            rejected = True
        audit = Audit(root / "audit.sqlite")
        audit.append("demo", "demo", tampered_bundle_rejected=rejected)
        return {
            "mode": "offline-demo; no LLM was called",
            "policy": evaluate_policy(),
            "tampered_bundle_rejected": rejected,
            "installed_version": state2["highest"],
            "rolled_back_to": store.load().version,
            "replay_high_watermark": store.state()["highest"],
            "audit": audit.verify(),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Skillbook operator CLI (local files only)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo")
    ev = sub.add_parser("evaluate")
    ev.add_argument("--live", action="store_true")
    inv = sub.add_parser("inventory")
    inv.add_argument("--observe-models", action="store_true")
    gen = sub.add_parser("keygen")
    gen.add_argument("--directory", type=Path, required=True)
    sg = sub.add_parser("sign")
    sg.add_argument("--payload", type=Path, required=True)
    sg.add_argument("--private-key", type=Path, required=True)
    sg.add_argument("--output", type=Path, required=True)
    for name in ("verify", "activate", "rollback"):
        item = sub.add_parser(name)
        item.add_argument("--public-key", type=Path, required=True)
        if name != "rollback":
            item.add_argument("--bundle", type=Path, required=True)
        if name != "verify":
            item.add_argument("--state", type=Path, required=True)
        if name == "rollback":
            item.add_argument("--release-id", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--database", type=Path, required=True)
    audit.add_argument("--expected-head")
    args = parser.parse_args()
    try:
        match args.command:
            case "demo":
                result = demo()
            case "evaluate":
                result = asyncio.run(evaluate_model(Settings())) if args.live else evaluate_policy()
            case "inventory":
                result = inventory(Settings(), args.observe_models)
            case "keygen":
                key = Ed25519PrivateKey.generate()
                # Refuse replacement. The signing key belongs on a separate trusted machine.
                write_new(
                    args.directory / "signing.key",
                    key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    ),
                )
                write_new(
                    args.directory / "trusted.pub",
                    key.public_key().public_bytes(
                        serialization.Encoding.PEM,
                        serialization.PublicFormat.SubjectPublicKeyInfo,
                    ),
                )
                result = {"generated": str(args.directory), "private_key_mode": "0600"}
            case "sign":
                key = serialization.load_pem_private_key(
                    read_bounded(args.private_key), password=None
                )
                if not isinstance(key, Ed25519PrivateKey):
                    raise ValueError("An Ed25519 private key is required")
                release = Release.model_validate_json(read_bounded(args.payload))
                write_new(args.output, sign(release, key))
                result = {"signed_version": release.version, "output": str(args.output)}
            case "verify":
                data = read_bounded(args.bundle)
                release = verify(data, public_key(args.public_key))
                result = {"verified_version": release.version, "bundle_sha256": digest(data)}
            case "activate" | "rollback":
                store = ReleaseStore(args.state, public_key(args.public_key))
                result = (
                    store.activate(read_bounded(args.bundle))
                    if args.command == "activate"
                    else (store.rollback(args.release_id))
                )
                result["restart_required"] = True
            case "audit":
                if not args.database.is_file():
                    raise ValueError("Audit database does not exist")
                result = Audit(args.database).verify(args.expected_head)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if args.command == "evaluate" and result.get("errors", 0):
            raise SystemExit(1)
    except Exception as exc:
        # Do not print response bodies or key material from third-party exceptions.
        parser.exit(
            1, f"Operation refused ({type(exc).__name__}); check inputs and local services.\n"
        )


if __name__ == "__main__":
    main()
