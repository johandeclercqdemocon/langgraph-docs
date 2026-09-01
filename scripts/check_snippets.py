"""Run every `uv run python -c "..."` snippet in the book and report failures.

    uv run python scripts/check_snippets.py

The book's claim is that its commands work. This checks it. Snippets that are
*meant* to raise (they demonstrate an error) are listed in EXPECT_FAILURE.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Snippets that demonstrate an error on purpose: a non-zero exit is the point.
EXPECT_FAILURE = {
    ("chapters/03-state-and-reducers.md", 2),  # provoke InvalidUpdateError
    ("chapters/16-debugging-mindset.md", 1),   # a deliberate 1/0 traceback
}

# The closing quote may be followed by shell plumbing (` 2>&1 | head -20`).
BLOCK = re.compile(r'```bash\nuv run [^\n]*python -c "(.*?)"[^\n]*\n```', re.DOTALL)


def main() -> int:
    failures: list[str] = []
    total = 0

    for md in sorted(ROOT.rglob("*.md")):
        if ".venv" in str(md):
            continue
        rel = md.relative_to(ROOT).as_posix()
        for i, m in enumerate(BLOCK.finditer(md.read_text()), 1):
            total += 1
            # Undo the shell escaping used inside the double-quoted -c argument.
            code = m.group(1).replace('\\"', '"').replace("\\$", "$")
            expect_fail = (rel, i) in EXPECT_FAILURE

            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT, capture_output=True, text=True, timeout=180,
            )
            ok = (proc.returncode != 0) if expect_fail else (proc.returncode == 0)
            status = "ok " if ok else "FAIL"
            print(f"[{status}] {rel} #{i}{'  (expected to raise)' if expect_fail else ''}")
            if not ok:
                tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
                failures.append(f"{rel} #{i}\n    " + "\n    ".join(tail))

    print(f"\n{total - len(failures)}/{total} snippets behaved as documented.")
    for f in failures:
        print("\n" + f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
