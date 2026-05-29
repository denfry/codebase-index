from __future__ import annotations

from codebase_index.config import Config
from codebase_index.discovery.walker import walk


def _walk_paths(root):
    cfg = Config()
    return {c.rel_path: c for c in walk(root, cfg)}


def test_walk_includes_source_excludes_unsafe(sample_repo):
    found = _walk_paths(sample_repo)

    assert "src/auth/token.py" in found
    assert "src/models/user.py" in found
    assert "web/app.ts" in found

    assert ".env" not in found
    assert "secrets.pem" not in found
    assert "logo.png" not in found
    assert "huge.json" not in found
    assert "node_modules/leftpad/index.js" not in found
    assert "dist/bundle.min.js" not in found
    assert found["src/schema.generated.ts"].is_generated is True


def test_candidate_fields(sample_repo):
    found = _walk_paths(sample_repo)
    c = found["src/auth/token.py"]
    assert c.lang == "python"
    assert c.parser == "treesitter"
    assert c.size_bytes > 0
    assert c.is_generated is False