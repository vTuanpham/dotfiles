import os
import stat

import pytest


@pytest.fixture(autouse=True)
def never_run_the_real_agy(tmp_path_factory, monkeypatch):
    """A test that reaches the agy CLI would open a Google sign-in browser on the owner's desktop."""
    stub = tmp_path_factory.mktemp("agy-stub") / "agy"
    stub.write_text("#!/bin/sh\necho 'tests must not run the real agy CLI' >&2\nexit 97\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{stub.parent}{os.pathsep}{os.environ.get('PATH', '')}")
