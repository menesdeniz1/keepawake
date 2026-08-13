import hashlib
import http.server
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QTimer

from updater import UpdateManager

FAKE_INSTALLER_BYTES = b"fake installer bytes for testing"
FAKE_INSTALLER_SHA256 = hashlib.sha256(FAKE_INSTALLER_BYTES).hexdigest()


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/manifest.json":
            body = (
                '{"version": "1.9.9", '
                '"url": "http://127.0.0.1:%d/installer.exe", '
                '"sha256": "%s"}' % (self.server.server_port, FAKE_INSTALLER_SHA256)
            ).encode("utf-8")
        elif self.path == "/installer.exe":
            body = FAKE_INSTALLER_BYTES
        else:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def local_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=2)


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication(sys.argv)


def _run_with_timeout(app, timeout_ms=8000):
    QTimer.singleShot(timeout_ms, app.quit)
    app.exec()


def test_update_available_flow(qapp, local_server, monkeypatch):
    port = local_server.server_port
    monkeypatch.setattr("updater.MANIFEST_URL", f"http://127.0.0.1:{port}/manifest.json")

    mgr = UpdateManager("1.0.0")
    result = {}
    mgr.update_available.connect(
        lambda v, u, s: (result.update(version=v, url=u, sha256=s), qapp.quit())
    )
    mgr.check_failed.connect(lambda r: (result.update(error=r), qapp.quit()))

    QTimer.singleShot(0, mgr.check)
    _run_with_timeout(qapp)

    assert result.get("version") == "1.9.9"
    assert result.get("sha256") == FAKE_INSTALLER_SHA256


def test_up_to_date_flow(qapp, local_server, monkeypatch):
    port = local_server.server_port
    monkeypatch.setattr("updater.MANIFEST_URL", f"http://127.0.0.1:{port}/manifest.json")

    mgr = UpdateManager("1.9.9")
    result = {}
    mgr.up_to_date.connect(lambda: (result.update(up_to_date=True), qapp.quit()))
    mgr.update_available.connect(
        lambda v, u, s: (result.update(unexpected=True), qapp.quit())
    )

    QTimer.singleShot(0, mgr.check)
    _run_with_timeout(qapp)

    assert result.get("up_to_date") is True


def test_download_correct_hash(qapp, local_server, tmp_path):
    port = local_server.server_port
    mgr = UpdateManager("1.0.0")
    result = {}
    mgr.download_finished.connect(lambda ok, p: (result.update(ok=ok, path=p), qapp.quit()))

    QTimer.singleShot(
        0,
        lambda: mgr.download(
            f"http://127.0.0.1:{port}/installer.exe", FAKE_INSTALLER_SHA256, tmp_path
        ),
    )
    _run_with_timeout(qapp)

    assert result["ok"] is True
    assert Path(result["path"]).read_bytes() == FAKE_INSTALLER_BYTES


def test_download_wrong_hash_rejected(qapp, local_server, tmp_path):
    port = local_server.server_port
    mgr = UpdateManager("1.0.0")
    result = {}
    mgr.download_finished.connect(lambda ok, p: (result.update(ok=ok, path=p), qapp.quit()))

    wrong_hash = "f" * 64
    QTimer.singleShot(
        0,
        lambda: mgr.download(f"http://127.0.0.1:{port}/installer.exe", wrong_hash, tmp_path),
    )
    _run_with_timeout(qapp)

    assert result["ok"] is False
    assert not (tmp_path / "KeepAwakeUpdate.exe").exists()


def test_download_requires_sha256(tmp_path):
    mgr = UpdateManager("1.0.0")
    with pytest.raises(ValueError):
        mgr.download("http://example.invalid/x.exe", "", tmp_path)
