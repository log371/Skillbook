import os

import pytest


@pytest.fixture(autouse=True)
def isolate_operator_environment(monkeypatch):
    for name in os.environ:
        if name.startswith("SKILLBOOK_"):
            monkeypatch.delenv(name)
