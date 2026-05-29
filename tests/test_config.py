from __future__ import annotations

import json

from codebase_index.config import Config, find_root, load


def test_find_root_walks_up_to_git(tmp_path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_root(nested) == tmp_path


def test_find_root_falls_back_to_start(tmp_path):
    nested = tmp_path / "x"
    nested.mkdir()
    assert find_root(nested) == nested


def test_load_defaults_when_no_config_file(tmp_path):
    (tmp_path / ".git").mkdir()
    cfg = load(tmp_path)
    assert isinstance(cfg, Config)
    assert cfg.max_file_bytes == 1_048_576
    assert cfg.embeddings.backend == "noop"


def test_load_honors_explicit_root_inside_git_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    fixture = tmp_path / "fixtures" / "sample"
    fixture.mkdir(parents=True)
    cfg = load(fixture)
    assert cfg.root == str(fixture.resolve())


def test_load_merges_config_json(tmp_path):
    (tmp_path / ".git").mkdir()
    cache = tmp_path / ".claude" / "cache" / "codebase-index"
    cache.mkdir(parents=True)
    (cache / "config.json").write_text(json.dumps({"max_file_bytes": 2048}), encoding="utf-8")
    cfg = load(tmp_path)
    assert cfg.max_file_bytes == 2048
    assert cfg.retrieval.rrf_k == 60


def test_config_hash_stable_and_sensitive():
    a = Config()
    b = Config()
    assert a.config_hash() == b.config_hash()
    c = Config(max_file_bytes=42)
    assert c.config_hash() != a.config_hash()
    d = Config()
    d.retrieval.token_budget = 9999
    assert d.config_hash() == a.config_hash()


def test_config_hash_changes_when_embeddings_toggled():
    off = Config()
    on = Config()
    on.embeddings.enabled = True
    assert off.config_hash() != on.config_hash()


def test_config_hash_changes_when_embedding_model_changes():
    a = Config()
    b = Config()
    b.embeddings.model = "some-other-model"
    assert a.config_hash() != b.config_hash()


def test_config_hash_ignores_external_endpoint():
    a = Config()
    b = Config()
    b.embeddings.endpoint = "https://example.test/embed"
    b.embeddings.allow_external = True
    assert a.config_hash() == b.config_hash()
