"""Working-tree validation: verdict states, relocation, and gate parity with the indexer."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from codebase_index.config import Config
from codebase_index.discovery.gates import PathGate
from codebase_index.discovery.walker import walk
from codebase_index.memory import identity as ident
from codebase_index.memory.validate import FileView, WorkingTree, locate, validate

BODY = "def total(items):\n    return sum(i.price for i in items)\n"


def _repo(tmp_path: Path, files: dict[str, str | bytes], **cfg) -> tuple[Path, WorkingTree]:
    root = tmp_path / "repo"
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="")
    root.mkdir(exist_ok=True)
    config = Config(**cfg)
    config.root = str(root)
    return root, WorkingTree(PathGate(root, config))


def _ref(root: Path, rel: str, start: int, end: int) -> ident.EvidenceRef:
    lines = ident.split_lines((root / rel).read_bytes())
    return ident.make_ref(rel, start, end, ident.span_sha(lines, start, end))


def _fresh(root: Path, config_kwargs: dict | None = None) -> WorkingTree:
    config = Config(**(config_kwargs or {}))
    config.root = str(root)
    return WorkingTree(PathGate(root, config))


def test_unchanged_evidence_is_valid(tmp_path):
    root, tree = _repo(tmp_path, {"src/cart.py": "import os\n\n" + BODY})
    ref = _ref(root, "src/cart.py", 3, 4)
    verdict = validate(ref, tree)
    assert verdict.state == "valid" and verdict.valid
    assert (verdict.line_start, verdict.line_end) == (3, 4)


def test_edit_elsewhere_in_the_file_keeps_the_span_valid(tmp_path):
    root, _ = _repo(tmp_path, {"src/cart.py": "import os\n\n" + BODY + "\nX = 1\n"})
    ref = _ref(root, "src/cart.py", 3, 4)
    (root / "src/cart.py").write_text("import os\n\n" + BODY + "\nX = 2\n", encoding="utf-8")
    assert validate(ref, _fresh(root)).state == "valid"


@pytest.mark.parametrize("with_hint", [True, False])
def test_insertion_above_relocates(tmp_path, with_hint):
    root, _ = _repo(tmp_path, {"src/cart.py": "import os\n\n" + BODY})
    ref = _ref(root, "src/cart.py", 3, 4)
    hint = ident.line_sha("def total(items):") if with_hint else None
    (root / "src/cart.py").write_text("import os\nimport sys\n\n\n" + BODY, encoding="utf-8")
    verdict = validate(ref, _fresh(root), first_line_sha=hint)
    assert verdict.state == "relocated" and verdict.valid
    assert (verdict.line_start, verdict.line_end) == (5, 6)


def test_body_change_invalidates(tmp_path):
    root, _ = _repo(tmp_path, {"src/cart.py": BODY})
    ref = _ref(root, "src/cart.py", 1, 2)
    (root / "src/cart.py").write_text(BODY.replace("sum(", "max("), encoding="utf-8")
    verdict = validate(ref, _fresh(root))
    assert verdict.state == "changed" and not verdict.valid


def test_whitespace_only_change_invalidates(tmp_path):
    root, _ = _repo(tmp_path, {"src/cart.py": BODY})
    ref = _ref(root, "src/cart.py", 1, 2)
    (root / "src/cart.py").write_text(BODY.replace("    return", "  return"), encoding="utf-8")
    assert validate(ref, _fresh(root)).state == "changed"


def test_crlf_conversion_is_not_a_change(tmp_path):
    root, _ = _repo(tmp_path, {"src/cart.py": BODY})
    ref = _ref(root, "src/cart.py", 1, 2)
    (root / "src/cart.py").write_bytes(BODY.replace("\n", "\r\n").encode())
    assert validate(ref, _fresh(root)).state == "valid"


def test_duplicated_content_is_ambiguous_not_valid(tmp_path):
    root, _ = _repo(tmp_path, {"src/cart.py": "# a\n" + BODY})
    ref = _ref(root, "src/cart.py", 2, 3)
    (root / "src/cart.py").write_text("# b\n\n" + BODY + BODY, encoding="utf-8")
    assert validate(ref, _fresh(root)).state == "ambiguous"


def test_deleted_file(tmp_path):
    root, _ = _repo(tmp_path, {"src/cart.py": BODY})
    ref = _ref(root, "src/cart.py", 1, 2)
    (root / "src/cart.py").unlink()
    assert validate(ref, _fresh(root)).state == "deleted"


def test_move_to_another_file_is_not_reused(tmp_path):
    root, _ = _repo(tmp_path, {"src/cart.py": BODY})
    ref = _ref(root, "src/cart.py", 1, 2)
    (root / "src/core").mkdir()
    (root / "src/cart.py").replace(root / "src/core/cart.py")
    assert validate(ref, _fresh(root)).state == "deleted"


def test_range_past_end_of_shortened_file_is_changed(tmp_path):
    root, _ = _repo(tmp_path, {"src/cart.py": BODY + "x = 1\n"})
    ref = _ref(root, "src/cart.py", 2, 3)
    (root / "src/cart.py").write_text("y = 2\n", encoding="utf-8")
    assert validate(ref, _fresh(root)).state == "changed"


@pytest.mark.parametrize(
    "rel,files,cfg",
    [
        (".env", {".env": "API_KEY=abc\n"}, {}),
        ("config/prod.pem", {"config/prod.pem": "-----BEGIN KEY-----\n"}, {}),
        ("node_modules/pkg/index.js", {"node_modules/pkg/index.js": "x\n"}, {}),
        ("build/out.py", {"build/out.py": "x\n"}, {}),
        ("private/notes.py", {"private/notes.py": "x\n", ".gitignore": "private/\n"}, {}),
        ("big.py", {"big.py": "x = 1\n" * 50}, {"max_file_bytes": 64}),
        ("blob.py", {"blob.py": b"x = 1\n\x00\x01"}, {}),
    ],
)
def test_gated_paths_are_excluded(tmp_path, rel, files, cfg):
    root, _ = _repo(tmp_path, files)
    ref = ident.EvidenceRef(rel, 1, 1, "0" * 16)
    verdict = validate(ref, _fresh(root, cfg))
    assert verdict.state == "excluded" and not verdict.valid


def test_name_gated_files_are_never_opened(tmp_path, monkeypatch):
    root, _ = _repo(tmp_path, {".env": "API_KEY=abc\n", "node_modules/a.js": "x\n"})
    opened: list[str] = []
    real = Path.read_bytes

    def spy(self):
        opened.append(self.name)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    tree = _fresh(root)
    for rel in (".env", "node_modules/a.js"):
        assert validate(ident.EvidenceRef(rel, 1, 1, "0" * 16), tree).state == "excluded"
    assert opened == []


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive filesystem check")
def test_case_variant_cannot_bypass_directory_gate(tmp_path):
    root, _ = _repo(tmp_path, {"node_modules/pkg/a.js": "module.exports = 1\n"})
    ref = ident.EvidenceRef("NODE_MODULES/pkg/a.js", 1, 1, "0" * 16)
    assert validate(ref, _fresh(root)).state == "excluded"


def test_symlink_outside_repository_is_excluded(tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = 1\n", encoding="utf-8")
    root, _ = _repo(tmp_path, {"src/keep.py": "x = 1\n"})
    try:
        os.symlink(outside, root / "src" / "link.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    ref = ident.EvidenceRef("src/link.py", 1, 1, "0" * 16)
    verdict = validate(ref, _fresh(root))
    assert verdict.state == "excluded" and "outside" in verdict.reason


def test_gate_admits_exactly_what_the_walker_indexes(sample_repo):
    """Security parity: validation can never read a file the indexer would refuse."""
    config = Config()
    config.root = str(sample_repo)
    walked = {c.rel_path for c in walk(sample_repo, config)}
    gate = PathGate(sample_repo, config)
    admitted = set()
    for path in Path(sample_repo).rglob("*"):
        if path.is_file():
            rel = path.relative_to(sample_repo).as_posix()
            if gate.read(rel).state == "ok":
                admitted.add(rel)
    assert admitted == walked
    assert "node_modules/leftpad/index.js" not in admitted


def test_locate_is_bounded_and_limited():
    view = FileView(["same"] * 50)
    sha = ident.span_sha(view.lines, 1, 2)
    assert locate(view, sha, 2, limit=2) == [1, 2]
    assert locate(view, sha, 2, max_steps=10) is None
    assert locate(view, sha, 99) == []


def test_bounded_search_failure_is_reported_invalid(tmp_path, monkeypatch):
    import codebase_index.memory.validate as mod

    root, _ = _repo(tmp_path, {"src/cart.py": "import os\n\n" + BODY})
    ref = _ref(root, "src/cart.py", 3, 4)
    (root / "src/cart.py").write_text("import os\nimport sys\n\n\n" + BODY, encoding="utf-8")
    monkeypatch.setattr(mod, "MAX_SCAN_STEPS", 1)
    verdict = mod.validate(ref, _fresh(root))
    assert verdict.state == "changed" and "too large" in verdict.reason
