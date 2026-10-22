"""Ghost inline previews and Windows-default media opening in WSL."""

import base64
import os
import secrets
import shlex
import shutil
import subprocess
import sys


def open_windows(files):
    for path in files:
        if not os.path.isfile(path):
            raise ValueError("Not a file: " + path)
        windows_path = subprocess.check_output(
            ["wslpath", "-w", os.path.abspath(path)], text=True
        ).strip()
        # Literal quoting keeps filenames out of PowerShell's expression parser.
        script = (
            "Start-Process -ErrorAction Stop -FilePath '"
            + windows_path.replace("'", "''")
            + "'"
        )
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded,
            ],
            check=True,
        )


if __name__ == "__main__":
    open_windows(sys.argv[1:])
else:
    import ranger.api
    from ranger.ext.img_display import (
        ImageDisplayer,
        ImageDisplayError,
        get_terminal_size,
        register_image_displayer,
    )

    @register_image_displayer("ghostwsl")
    class GhostWSLImageDisplayer(ImageDisplayer):
        def __init__(self):
            self.image_id = secrets.randbelow(4294967295) + 1

        def draw(self, path, start_x, start_y, width, height):
            rows, cols, pixels_x, pixels_y = get_terminal_size()
            if not all((rows, cols, pixels_x, pixels_y)):
                raise ImageDisplayError(
                    "Ghost did not report terminal pixel dimensions"
                )
            sys.stdout.write("\0337")
            sys.stdout.flush()
            try:
                subprocess.run(
                    [
                        "kitten",
                        "icat",
                        "--stdin=no",
                        "--transfer-mode=stream",
                        "--passthrough=none",
                        "--loop=0",
                        "--image-id=" + str(self.image_id),
                        "--use-window-size={},{},{},{}".format(
                            cols, rows, pixels_x, pixels_y
                        ),
                        "--place={}x{}@{}x{}".format(width, height, start_x, start_y),
                        path,
                    ],
                    stdin=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    check=True,
                    timeout=10,
                )
            except subprocess.CalledProcessError as error:
                raise ImageDisplayError(
                    error.stderr.decode("utf-8", errors="replace")
                ) from error
            except subprocess.TimeoutExpired as error:
                raise ImageDisplayError("Image preview timed out") from error
            finally:
                sys.stdout.write("\0338")
                sys.stdout.flush()

        def clear(self, start_x, start_y, width, height):
            sys.stdout.write("\033_Ga=d,d=I,i={},q=2;\033\\".format(self.image_id))
            sys.stdout.flush()

        def quit(self):
            self.clear(0, 0, 0, 0)

    previous_hook_init = ranger.api.hook_init

    def hook_init(fm):
        previous_hook_init(fm)
        if not os.environ.get("WSL_DISTRO_NAME"):
            return
        if (
            os.environ.get("TERM") == "xterm-ghostty"
            and not os.environ.get("TMUX")
            and shutil.which("kitten")
        ):
            # shortcut: the installed Kitty backend rejects Ghost; remove when it supports this WSL build.
            fm.settings.preview_images_method = "ghostwsl"
            fm.settings.preview_images = True
        if shutil.which("powershell.exe"):
            command = '{} {} "$@"'.format(
                shlex.quote(sys.executable), shlex.quote(__file__)
            )
            fm.rifle.rules.insert(
                0, (command, (("mime", "^(image|audio|video)/"), ("label", "windows")))
            )

    ranger.api.hook_init = hook_init
