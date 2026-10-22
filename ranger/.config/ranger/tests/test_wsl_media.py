import base64
import importlib.util
import io
import os
import subprocess
from pathlib import Path

import ranger
from types import SimpleNamespace
from unittest.mock import patch

from ranger.ext.rifle import Rifle

path = str(Path(__file__).resolve().parents[1] / "plugins" / "wsl_media.py")
spec = importlib.util.spec_from_file_location("wsl_media_check", path)
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

for environment, preview, opening in (
    ({"WSL_DISTRO_NAME": "Ubuntu", "TERM": "xterm-ghostty"}, True, True),
    ({"WSL_DISTRO_NAME": "Ubuntu", "TERM": "xterm-256color"}, False, True),
    ({"WSL_DISTRO_NAME": "Ubuntu", "TERM": "xterm-ghostty", "TMUX": "session"}, False, True),
    ({"TERM": "xterm-ghostty"}, False, False),
):
    rifle = Rifle(str(Path(ranger.__file__).parent / "config" / "rifle.conf"))
    rifle.reload_config()
    original = rifle.rules[:]
    fm = SimpleNamespace(settings=SimpleNamespace(preview_images=False), rifle=rifle)
    with patch.dict(os.environ, environment, clear=True), patch.object(plugin.shutil, "which", return_value="installed"):
        plugin.hook_init(fm)
    assert fm.settings.preview_images == preview
    assert rifle.rules[int(opening):] == original
    if opening:
        for mime in ("image/png", "image/svg+xml", "audio/mpeg", "video/mp4"):
            assert next(rifle.list_commands(["/tmp/image.png"], mimetype=mime))[2] == "windows"
        assert next(rifle.list_commands(["/tmp/code.txt"], mimetype="text/plain"))[2] == "editor"

display = plugin.GhostWSLImageDisplayer()
with patch.object(plugin, "get_terminal_size", return_value=(51, 191, 1910, 1020)), patch.object(plugin.subprocess, "run") as run, patch.object(plugin.sys, "stdout", new=io.StringIO()) as output:
    display.draw("/tmp/image with spaces.png", 90, 2, 80, 40)
    arguments = run.call_args.args[0]
    assert "--stdin=no" in arguments and "--transfer-mode=stream" in arguments
    assert "--use-window-size=191,51,1910,1020" in arguments
    assert "--place=80x40@90x2" in arguments
    assert arguments[-1] == "/tmp/image with spaces.png"
    display.clear(90, 2, 80, 40)
    assert "d=I,i=" + str(display.image_id) in output.getvalue()

with patch.object(plugin.os.path, "isfile", return_value=True), patch.object(plugin.subprocess, "check_output", return_value="C:\\Media\\Tuan's $photo & ảnh.png\n"), patch.object(plugin.subprocess, "run") as run:
    plugin.open_windows(["first.png", "second.png"])
    assert run.call_count == 2
    script = base64.b64decode(run.call_args.args[0][-1]).decode("utf-16-le")
    assert script == "Start-Process -ErrorAction Stop -FilePath 'C:\\Media\\Tuan''s $photo & ảnh.png'"
with patch.object(plugin.os.path, "isfile", return_value=False), patch.object(plugin.subprocess, "run") as run:
    try:
        plugin.open_windows(["missing.png"])
        raise AssertionError("missing file accepted")
    except ValueError:
        pass
    run.assert_not_called()
with patch.object(plugin, "get_terminal_size", return_value=(51, 191, 1910, 1020)), patch.object(plugin.subprocess, "run", side_effect=subprocess.TimeoutExpired("kitten", 10)), patch.object(plugin.sys, "stdout", new=io.StringIO()) as output:
    try:
        display.draw("image.png", 1, 1, 10, 10)
        raise AssertionError("timeout swallowed")
    except plugin.ImageDisplayError:
        pass
    assert output.getvalue().endswith("\0338")
print("Ranger media checks passed: terminal scoping, media routing, streamed previews, filename quoting and errors")
