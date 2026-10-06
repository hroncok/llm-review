#!/usr/bin/env python3
"""Generate the fedora-package-review SKILL.md variants from shared fragments.

Both variants (Koji-task input and Copr/PR input) share most of their review
logic (rpmlint, license verification, guideline checks, report template) --
that content lives once in ``skills/_fragments/`` and gets assembled here,
instead of being hand-duplicated across two SKILL.md files. See AGENTS.md's
"The skills" section for the convention this implements.

Run directly to (re)generate the committed SKILL.md files:

    python scripts/build_skills.py

``tests/unit/test_build_skills.py`` regenerates in-memory and asserts the
result matches what's committed, so editing a generated SKILL.md by hand
instead of its fragments gets caught.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRAGMENTS_DIR = REPO_ROOT / "skills" / "_fragments"

_CI_INTRO = (
    "Review a package build for Fedora against the packaging guidelines. This is the\n"
    "unattended, CI variant of the review skill: there is no human present to answer\n"
    "questions, so every step here must be self-contained."
)

# Each entry fully describes one generated skill: the output directory under
# `skills/`, its SKILL.md frontmatter, title, and the ordered list of
# fragment files (from FRAGMENTS_DIR) that make up its body.
SKILLS: list[dict] = [
    {
        "output_dir": "fedora-package-review-koji",
        "name": "fedora-package-review-koji",
        "description": (
            "Review a Fedora package build against the Fedora Packaging "
            "Guidelines. Reads guidelines from a local checkout, inspects "
            "downloaded SRPM/RPM artifacts, verifies licenses (including "
            "bundled/minified code), and produces a structured review "
            "report written to $REVIEW_OUTPUT_PATH."
        ),
        "title": "Fedora Package Review (CI variant)",
        "intro": _CI_INTRO,
        "fragments": [
            "input-koji.md",
            "guidelines.md",
            "inventory-koji.md",
            "cannot-review.md",
            "review-steps.md",
        ],
    },
    {
        "output_dir": "fedora-package-review-copr",
        "name": "fedora-package-review-copr",
        "description": (
            "Review a single package proposed via the Fedora Package Review "
            "Process (a PR adding a <name>/<name>.spec subdirectory), built "
            "in Copr. Reads guidelines from a local checkout, inspects the "
            "downloaded SRPM/RPM artifacts for one chroot, verifies "
            "licenses, and produces a structured review report written to "
            "$REVIEW_OUTPUT_PATH."
        ),
        "title": "Fedora Package Review (Copr/PR CI variant)",
        "intro": _CI_INTRO,
        "fragments": [
            "input-copr.md",
            "guidelines.md",
            "inventory-copr.md",
            "cannot-review.md",
            "review-steps.md",
        ],
    },
]


def render_skill(spec: dict, fragments_dir: Path = FRAGMENTS_DIR) -> str:
    """Assemble one SKILL.md's full text from ``spec`` and its fragments."""
    frontmatter = f"---\nname: {spec['name']}\ndescription: {spec['description']}\n---"
    title = f"# {spec['title']}"
    blocks = [frontmatter, title, spec["intro"].strip()]
    for fragment_name in spec["fragments"]:
        text = (fragments_dir / fragment_name).read_text()
        blocks.append(text.strip("\n"))
    return "\n\n".join(blocks) + "\n"


def generated_skills(fragments_dir: Path = FRAGMENTS_DIR) -> dict[str, str]:
    """Return ``{output_dir: rendered SKILL.md text}`` for every skill in SKILLS."""
    return {spec["output_dir"]: render_skill(spec, fragments_dir) for spec in SKILLS}


def write_all(repo_root: Path = REPO_ROOT) -> None:
    for output_dir, content in generated_skills(repo_root / "skills" / "_fragments").items():
        skill_dir = repo_root / "skills" / output_dir
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content)


if __name__ == "__main__":
    write_all()
