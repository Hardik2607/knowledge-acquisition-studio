import shutil
import tempfile
from pathlib import Path

from kas.adapters.git import GitAdapter
from kas.manifest import Source


def test_git_adapter_local_repo():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_src = tmp_path / "mock_repo"
        repo_src.mkdir()
        
        # Create mock README and config
        (repo_src / "README.md").write_text(
            "# Mock Agent Tool\n\n"
            "This tool provides autonomous deployment capabilities.\n\n"
            "## Installation\n\n"
            "Run `pip install mock-agent-tool` to install dependencies.\n\n"
            "## Usage\n\n"
            "Execute `mock-tool deploy --env prod` to launch deployment.\n",
            encoding="utf-8",
        )
        (repo_src / "pyproject.toml").write_text(
            "[project]\nname = 'mock-agent-tool'\nversion = '0.1.0'\n",
            encoding="utf-8",
        )

        adapter = GitAdapter()
        source = Source(
            kind="git",
            origin=str(repo_src),
            title="Mock Agent Tool",
        )
        workdir = tmp_path / "workdir"
        fetched = adapter.fetch(source, workdir)

        assert fetched.media_type == "application/x-git"
        assert fetched.raw_file.is_file()
        assert fetched.transcript is not None
        assert len(fetched.transcript.segments) > 0
        texts = " ".join(s.text for s in fetched.transcript.segments)
        assert "Installation" in texts
        assert "mock-agent-tool" in texts
