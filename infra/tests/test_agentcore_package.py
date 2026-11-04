"""The archive does not depend on file mtimes or installer-local paths."""

import importlib.util
import os
from pathlib import Path
from zipfile import ZipFile

spec = importlib.util.spec_from_file_location(
    "agentcore_package", Path(__file__).parents[1] / "package_agentcore.py"
)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def test_archive_is_deterministic_and_excludes_installer_paths(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("x = 1\n")
    (source / "bin").mkdir()
    (source / "bin/command").write_text("#!/random/temporary/path/python\n")
    (source / "example.dist-info").mkdir()
    (source / "example.dist-info/RECORD").write_text("temporary/install/path")
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    package.write_archive(source, first)
    os.utime(source / "app.py", (1600000000, 1600000000))
    package.write_archive(source, second)
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        assert archive.namelist() == ["app.py"]
        assert archive.getinfo("app.py").date_time == (1980, 1, 1, 0, 0, 0)
