from __future__ import annotations

import os
from pathlib import Path

from scripts._env_utils import load_env_file


def test_load_env_file_accepts_shell_export_and_infers_ir_search_path(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "ir_search").mkdir()
    (tmp_path / "ir_search" / "__init__.py").write_text("", encoding="utf-8")
    env_file = tmp_path / "ir_search.env"
    env_file.write_text(
        """
export WECHAT_OPENCLI_COMMAND="python tools/gzh_fetch.py --opencli"
BOCHA_API_KEY='dummy'
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WECHAT_OPENCLI_COMMAND", raising=False)
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)
    monkeypatch.delenv("IR_SEARCH_PATH", raising=False)

    loaded = load_env_file(str(env_file))

    assert loaded == env_file
    assert os.environ["WECHAT_OPENCLI_COMMAND"] == "python tools/gzh_fetch.py --opencli"
    assert os.environ["BOCHA_API_KEY"] == "dummy"
    assert os.environ["IR_SEARCH_PATH"] == str(tmp_path)


def test_load_env_file_does_not_override_existing_env(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "ir_search.env"
    env_file.write_text("export WECHAT_OPENCLI_COMMAND=new\n", encoding="utf-8")
    monkeypatch.setenv("WECHAT_OPENCLI_COMMAND", "existing")

    load_env_file(str(env_file))

    assert os.environ["WECHAT_OPENCLI_COMMAND"] == "existing"
