"""Check that this book's code and links still work.

    python scripts/check_snippets.py          # static checks + safe execution
    python scripts/check_snippets.py --run    # also execute shell commands (see below)

Four checks, all mechanical and all zero-false-positive by design:

  links     every relative markdown link resolves to a file that exists
  shell     every ```bash block parses (`bash -n`) -- catches broken quoting,
            heredocs and substitutions
  files     every `-f path/to/file` referenced by a command exists in the repo
  python    every `python -c "..."` block runs and exits as documented

Deliberately NOT checked: whether a command is marked destructive. These books
mark `**destructive**` by judgement -- deleting data you might care about, not
routine cleanup of resources the chapter just created -- so a mechanical rule
produces hundreds of false positives and trains you to ignore the output.

`--run` executes shell commands against a live environment (Docker daemon, kind
cluster). It is opt-in because those commands are real, some are slow, and some
delete things. Blocks preceded by a destructive marker are skipped even then.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

BASH_BLOCK = re.compile(r"```bash\n(.*?)```", re.DOTALL)
PY_BLOCK = re.compile(r'```bash\n(?:uv run )?[^\n]*python -c "(.*?)"[^\n]*\n```', re.DOTALL)
LINK = re.compile(r"\[[^\]]*\]\(([^)#]+?)(?:#[^)]*)?\)")
FILE_REF = re.compile(r"-f\s+((?:examples|manifests)/[^\s\"']+)")

# Snippets that demonstrate an error on purpose: a non-zero exit is the point.
EXPECT_FAILURE: set[tuple[str, int]] = {
    ("chapters/03-state-and-reducers.md", 2),
    ("chapters/16-debugging-mindset.md", 1),
}


def markdown_files() -> list[pathlib.Path]:
    return [
        p for p in sorted(ROOT.rglob("*.md"))
        if not any(part in {".git", ".venv", "node_modules"} for part in p.parts)
    ]


def check_links(fails: list[str]) -> int:
    n = 0
    for md in markdown_files():
        for link in LINK.findall(md.read_text()):
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            n += 1
            if not (md.parent / link).resolve().exists():
                fails.append(f"broken link  {md.relative_to(ROOT)} -> {link}")
    return n


def check_shell(fails: list[str]) -> int:
    n = 0
    for md in markdown_files():
        for i, m in enumerate(BASH_BLOCK.finditer(md.read_text()), 1):
            n += 1
            proc = subprocess.run(["bash", "-n"], input=m.group(1), capture_output=True, text=True)
            if proc.returncode != 0:
                first = (proc.stderr.strip().splitlines() or ["?"])[0]
                fails.append(f"shell syntax {md.relative_to(ROOT)} #{i}: {first[:90]}")
    return n


def check_file_refs(fails: list[str]) -> int:
    n = 0
    for md in markdown_files():
        # Only look inside ```bash blocks: prose mentions paths like `examples/...`.
        commands = "\n".join(BASH_BLOCK.findall(md.read_text()))
        for ref in sorted(set(FILE_REF.findall(commands))):
            if "..." in ref:
                continue
            n += 1
            if not (ROOT / ref).exists():
                fails.append(f"missing file {md.relative_to(ROOT)} -> {ref}")
    return n


def check_python(fails: list[str]) -> int:
    n = 0
    for md in markdown_files():
        rel = md.relative_to(ROOT).as_posix()
        for i, m in enumerate(PY_BLOCK.finditer(md.read_text()), 1):
            n += 1
            code = m.group(1).replace('\\"', '"').replace("\\$", "$")
            expect_fail = (rel, i) in EXPECT_FAILURE
            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT, capture_output=True, text=True, timeout=300,
            )
            ok = (proc.returncode != 0) if expect_fail else (proc.returncode == 0)
            if not ok:
                tail = ((proc.stderr or proc.stdout).strip().splitlines() or ["?"])[-1]
                fails.append(f"python      {rel} #{i}: {tail[:90]}")
    return n


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true",
                        help="also execute shell commands against a live environment")
    args = parser.parse_args()

    # Fail fast and clearly: run under the wrong interpreter and every snippet
    # reports ModuleNotFoundError, which looks like 48 book bugs rather than one
    # invocation mistake.
    try:
        import langgraph  # noqa: F401
    except ImportError:
        print("langgraph is not importable by this interpreter:\n"
              f"  {sys.executable}\n\n"
              "Run it through the project environment instead:\n"
              "  uv run python scripts/check_snippets.py")
        return 2

    fails: list[str] = []
    counts = {
        "links": check_links(fails),
        "shell blocks": check_shell(fails),
        "file refs": check_file_refs(fails),
        "python snippets": check_python(fails),
    }

    for label, n in counts.items():
        print(f"  {n:5} {label} checked")

    if args.run:
        print("\n  --run is not implemented for this book: every example here is Python\n"
              "  and is already executed above.")

    if fails:
        print(f"\n{len(fails)} problem(s):\n")
        for f in fails:
            print("  " + f)
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
