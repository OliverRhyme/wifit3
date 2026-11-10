#!/usr/bin/env python3
"""Cut a Termux fork release: bump ``<upstream>+termux.<n>``, commit, tag, optionally push.

The fork version is a PEP 440 local version: the upstream version it is based on, plus the fork's
own release counter. Pushing the ``v<version>`` tag fires .github/workflows/release.yml.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INIT = ROOT / "src" / "wifit3" / "__init__.py"
BRANCH = "termux-port"
REMOTE = "fork"
USAGE = "usage: release.py [--push] [--remote NAME]"


def git(*args):
    result = subprocess.run(("git", *args), cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        sys.exit(f"git {' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def upstream_base() -> str:
    source = git("show", "upstream/master:src/wifit3/__init__.py")
    match = re.search(r'__version__ = "(\d+\.\d+\.\d+)"', source)
    if match is None:
        sys.exit("no __version__ literal in upstream/master")
    return match.group(1)


def main() -> None:
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(USAGE)
        return
    unknown = [a for a in args if a.startswith("-") and a not in ("--push", "--remote")]
    if unknown:
        sys.exit(f"unknown flag(s): {' '.join(unknown)}\n{USAGE}")
    remote = REMOTE
    if "--remote" in args:
        index = args.index("--remote")
        if index + 1 >= len(args) or args[index + 1].startswith("-"):
            sys.exit(f"--remote needs a name\n{USAGE}")
        remote = args[index + 1]
    push = "--push" in args

    if git("status", "--porcelain", "--untracked-files=no"):
        sys.exit("tracked changes present: commit or stash first")
    if git("rev-parse", "--abbrev-ref", "HEAD") != BRANCH:
        sys.exit(f"not on {BRANCH}")
    if subprocess.run(("git", "merge-base", "--is-ancestor", "upstream/master", "HEAD"),
                      cwd=ROOT).returncode:
        sys.exit("upstream/master is not merged: sync upstream first")

    source = INIT.read_text(encoding="utf-8")
    match = re.search(r'__version__ = "(\d+\.\d+\.\d+)(?:\+termux\.(\d+))?"', source)
    if match is None:
        sys.exit(f"no __version__ literal in {INIT}")
    base, revision = match.group(1), int(match.group(2) or 0)
    upstream = upstream_base()
    if base != upstream:
        sys.exit(f"version base {base} does not match upstream {upstream}: sync and resolve first")

    version = f"{upstream}+termux.{revision + 1}"
    tag = f"v{version}"
    if tag in git("tag", "-l").split():
        sys.exit(f"{tag} already exists")

    INIT.write_text(source[: match.start()] + f'__version__ = "{version}"'
                    + source[match.end():], encoding="utf-8")
    git("add", str(INIT))
    git("commit", "-m", f"chore(release): wifit3 {version}")
    git("tag", tag)
    previous = f"{base}+termux.{revision}" if revision else base
    print(f"{previous} -> {version}  (tagged {tag})")
    if push:
        git("push", remote, BRANCH, tag)
        print(f"pushed to {remote}. Release workflow now building {tag}.")
    else:
        print(f"next: git push {remote} {BRANCH} {tag}")


if __name__ == "__main__":
    main()
