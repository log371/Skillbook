import json
import sys

import pytest

from skillbook.cli import demo, main


def invoke(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["skillbook", *map(str, args)])
    main()
    return json.loads(capsys.readouterr().out)


def test_offline_demo():
    report = demo()
    assert report["policy"]["passed"] == report["policy"]["total"]
    assert report["tampered_bundle_rejected"]
    assert report["rolled_back_to"] == 1
    assert report["replay_high_watermark"] == 2


def test_key_sign_verify_activate_cli(tmp_path, monkeypatch, capsys):
    from skillbook.app import demo_release

    payload = tmp_path / "payload.json"
    payload.write_text(demo_release().model_dump_json())
    keys, bundle, state = tmp_path / "keys", tmp_path / "bundle.json", tmp_path / "state"
    invoke(monkeypatch, capsys, "keygen", "--directory", keys)
    assert (keys / "signing.key").stat().st_mode & 0o777 == 0o600
    invoke(
        monkeypatch,
        capsys,
        "sign",
        "--payload",
        payload,
        "--private-key",
        keys / "signing.key",
        "--output",
        bundle,
    )
    report = invoke(
        monkeypatch, capsys, "verify", "--bundle", bundle, "--public-key", keys / "trusted.pub"
    )
    assert report["verified_version"] == 1
    invoke(
        monkeypatch,
        capsys,
        "activate",
        "--bundle",
        bundle,
        "--public-key",
        keys / "trusted.pub",
        "--state",
        state,
    )
    rollback = invoke(
        monkeypatch,
        capsys,
        "rollback",
        "--release-id",
        report["bundle_sha256"],
        "--public-key",
        keys / "trusted.pub",
        "--state",
        state,
    )
    assert rollback["restart_required"]
    monkeypatch.setattr(sys, "argv", ["skillbook", "keygen", "--directory", str(keys)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
