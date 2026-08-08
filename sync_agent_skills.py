#!/usr/bin/env python3
"""Mirror project agent skills into the directories each coding agent discovers.

Claude Code, Google Antigravity and Gemini CLI all read the same SKILL.md format,
but each looks in its own project-level folder. Rather than maintain three copies
by hand, the canonical skill lives under .claude/skills/ and this script copies it
to the others.

    python sync_agent_skills.py           # sync all skills
    python sync_agent_skills.py --check   # exit 1 if any target is out of date

Copies rather than symlinks, because symlinks in a git checkout do not survive on
Windows without developer mode.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# The canonical location we author in.
SOURCE = REPO_ROOT / ".claude" / "skills"

# Where each agent looks for project-level skills.
TARGETS = {
    "Antigravity": REPO_ROOT / ".agents" / "skills",
    "Gemini CLI": REPO_ROOT / ".gemini" / "skills",
}


def skill_dirs() -> list[Path]:
    """Every directory under SOURCE that actually contains a SKILL.md."""
    return sorted(p.parent for p in SOURCE.glob("*/SKILL.md"))


def is_in_sync(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return False
    comparison = filecmp.dircmp(src, dst)
    stack = [comparison]
    while stack:
        node = stack.pop()
        if node.left_only or node.right_only or node.diff_files or node.funny_files:
            return False
        stack.extend(node.subdirs.values())
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift without writing anything; exit 1 if out of date",
    )
    args = parser.parse_args()

    skills = skill_dirs()
    if not skills:
        print(f"No skills found under {SOURCE.relative_to(REPO_ROOT)}/")
        return 0

    drifted = False
    for agent, target_root in TARGETS.items():
        for skill in skills:
            destination = target_root / skill.name
            if is_in_sync(skill, destination):
                print(f"  ok      {agent}: {skill.name}")
                continue

            drifted = True
            if args.check:
                print(f"  DRIFT   {agent}: {skill.name}")
                continue

            if destination.exists():
                shutil.rmtree(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(skill, destination)
            print(f"  synced  {agent}: {skill.name}")

    if args.check and drifted:
        print("\nSkill copies are out of date. Run: python sync_agent_skills.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
