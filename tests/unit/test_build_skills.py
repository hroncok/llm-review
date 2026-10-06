import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "build_skills.py"
_spec = importlib.util.spec_from_file_location("build_skills", _SCRIPT_PATH)
build_skills = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_skills)


def test_generated_skills_match_committed_files():
    """Catch a hand-edit of a generated SKILL.md instead of its fragments.

    Regenerates every skill in-memory from skills/_fragments/ and compares
    against what's actually committed under skills/<name>/SKILL.md.
    """
    for output_dir, expected in build_skills.generated_skills().items():
        committed_path = build_skills.REPO_ROOT / "skills" / output_dir / "SKILL.md"
        assert committed_path.read_text() == expected, (
            f"skills/{output_dir}/SKILL.md is out of date with skills/_fragments/ -- "
            "run `python scripts/build_skills.py` to regenerate it"
        )
