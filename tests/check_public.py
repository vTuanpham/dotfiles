"""Keep this repository public-facing: refuse secrets, personal identifiers and machine-local state.

    python3 tests/check_public.py --staged    the lines about to be committed (what the pre-commit hook runs)
    python3 tests/check_public.py --changed   everything that differs from HEAD, new files included: what a tool
                                              or an installer wrote into a linked file since the last commit
    python3 tests/check_public.py             every tracked file

Only added lines are judged, so old content never blocks a commit. Personal names that must never appear
(your email, real name, private project names) live outside the repository, one per line, in
~/.config/dotfiles/private-terms.txt (override with DOTFILES_PRIVATE_TERMS); a file that lists them
cannot itself be tracked. Prints where and why, never the matching text."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

SECRET = re.compile(
    r"sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|BEGIN [A-Z ]*PRIVATE KEY|[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}"
    r"|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"
    # a name = a long value that has a digit in it (a real key does; `secrets.token_urlsafe` does not)
    r"|(?:api[_-]?key|secret|token|passwd|password|bearer)[A-Za-z_]*[\"']?\s*[=:]\s*[\"']?"
    r"(?=[A-Za-z0-9/+_=.-]*\d)[A-Za-z0-9/+_=.-]{20,}",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.([A-Za-z]{2,}))")
OK_EMAIL_DOMAINS = ("users.noreply.github.com", "anthropic.com", "github.com", "example.com")
NOT_A_TLD = {"png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "css", "js", "json", "lock", "md", "py", "ts"}
MACHINE_LOCAL = re.compile(r'^\s*\[projects\.|^\s*\[hooks\.state|"trustedWorkspaces"|trusted_hash')
BAD_NAME = re.compile(
    r"(^|/)(auth\.json|\.credentials\.json|\.env(\..*)?|\.netrc|\.git-credentials|id_(rsa|ed25519)(\.pub)?"
    r"|[^/]*\.(pem|key|sqlite3?|db)|[^/]*cookies[^/]*\.json|secrets\.local\.sh)$"
)
SELF = {"tests/check_public.py", "tests/test_public.py"}  # they spell out the very patterns they look for


def private_terms():
    path = Path(os.environ.get("DOTFILES_PRIVATE_TERMS", "~/.config/dotfiles/private-terms.txt")).expanduser()
    if not path.is_file():
        return []
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line.lower() for line in lines if line and not line.startswith("#")]


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def whole_files(root, paths):
    for path in paths:
        file = Path(root) / path
        if file.is_file() and not file.is_symlink():
            data = file.read_bytes()
            if b"\0" in data[:8192]:  # images and other binaries: a pattern in pixels is noise; review by hand
                continue
            for number, text in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                yield path, number, text


def changed_names(root, mode):
    """The files each mode looks at: tracked ones, the staged ones, or everything that differs from HEAD."""
    if mode == "all":
        return git(root, "ls-files").splitlines()
    if mode == "staged":
        return git(root, "diff", "--cached", "--name-only", "--diff-filter=AMR").splitlines()
    tracked = git(root, "diff", "HEAD", "--name-only", "--diff-filter=AMR").splitlines()
    return tracked + git(root, "ls-files", "--others", "--exclude-standard").splitlines()


def added_lines(root, mode):
    """(path, line number, text) for every added line; whole files for "all" and for untracked ones."""
    if mode == "all":
        yield from whole_files(root, changed_names(root, mode))
        return
    base = ["--cached"] if mode == "staged" else ["HEAD"]
    path, number = None, 0
    for line in git(root, "diff", *base, "-U0", "--no-color", "--diff-filter=AMR").splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@"):
            number = int(re.search(r"\+(\d+)", line).group(1)) - 1
        elif line.startswith("+") and not line.startswith("+++"):
            number += 1
            yield path, number, line[1:]
    if mode == "changed":  # a new, untracked file is all added lines
        yield from whole_files(root, git(root, "ls-files", "--others", "--exclude-standard").splitlines())


def problems(root, mode):
    terms = private_terms()
    found = []
    for path in changed_names(root, mode):
        if path not in SELF and BAD_NAME.search(path):
            found.append((path, 0, "a credential or state file does not belong in a public repo"))
    for path, number, text in added_lines(root, mode):
        if path in SELF:
            continue
        lower = text.lower()
        if SECRET.search(text):
            found.append((path, number, "looks like a secret"))
        for match in EMAIL.finditer(text):  # test fixtures use made-up addresses; the private terms catch real ones
            domain, tld = match.group(1).lower(), match.group(2).lower()
            if tld not in NOT_A_TLD and not domain.endswith(OK_EMAIL_DOMAINS) and "/tests/" not in f"/{path}":
                found.append((path, number, "an email address (use the GitHub no-reply one)"))
        if Path(path).suffix in {".toml", ".json", ".jsonc"} and MACHINE_LOCAL.search(text):
            found.append((path, number, "machine-local state (trusted projects, hook hashes); leave it untracked"))
        if any(term in lower for term in terms):
            found.append((path, number, "a name from your private-terms list"))
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--staged", action="store_const", dest="mode", const="staged", help="what is staged for commit")
    modes.add_argument("--changed", action="store_const", dest="mode", const="changed", help="everything that differs from HEAD, untracked files included")
    parser.add_argument("--root", default=Path(__file__).resolve().parents[1], help="repository to check")
    args = parser.parse_args()
    found = problems(args.root, args.mode or "all")
    for path, number, why in found:
        print(f"{path}:{number}: {why}", file=sys.stderr)
    if found:
        print(
            f"\n{len(found)} problem(s). This repository is public: keep personal details, project names and\n"
            "machine-local state out of it (see AGENTS.md). Fix them, or edit the live file instead of\n"
            "snapshotting it.",
            file=sys.stderr,
        )
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
