import hashlib
import json
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

MANIFEST_URL = (
    "https://raw.githubusercontent.com/menesdeniz1/keepawake/main/latest.json"
)


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.strip().split("."))


def is_newer(remote_version: str, current_version: str) -> bool:
    return parse_version(remote_version) > parse_version(current_version)


def _enable_redirects(request: QNetworkRequest) -> None:
    # GitHub Release asset indirmeleri 302 ile yönlendirir; manifest
    # (raw.githubusercontent.com) genelde yönlendirmez ama zararı yok.
    request.setAttribute(
        QNetworkRequest.Attribute.RedirectPolicyAttribute,
        QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
    )


class UpdateManager(QObject):
    """latest.json'u kontrol eder, gerekirse indirir/doğrular."""

    update_available = Signal(str, str, str)  # version, url, sha256
    up_to_date = Signal()
    check_failed = Signal(str)
    download_finished = Signal(bool, str)  # success, path_or_error

    def __init__(self, current_version: str, parent: QObject | None = None):
        super().__init__(parent)
        self.current_version = current_version
        self.manager = QNetworkAccessManager(self)
        self._check_reply: QNetworkReply | None = None
        self._download_reply: QNetworkReply | None = None
        self._download_expected_sha256 = ""
        self._download_dest: Path | None = None

    def check(self) -> None:
        if self._check_reply is not None:
            return

        request = QNetworkRequest(QUrl(MANIFEST_URL))
        _enable_redirects(request)
        self._check_reply = self.manager.get(request)
        self._check_reply.finished.connect(self._on_check_finished)

    def _on_check_finished(self) -> None:
        reply = self._check_reply
        self._check_reply = None
        if reply is None:
            return

        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.check_failed.emit(reply.errorString())
                return

            try:
                payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
                remote_version = str(payload["version"])
                url = str(payload["url"])
                sha256 = str(payload.get("sha256", "")).strip().lower()
            except (ValueError, KeyError):
                self.check_failed.emit("Güncelleme bilgisi (latest.json) okunamadı.")
                return

            try:
                newer = is_newer(remote_version, self.current_version)
            except ValueError:
                self.check_failed.emit("Sürüm formatı okunamadı.")
                return

            if not newer:
                self.up_to_date.emit()
                return

            if not url or not sha256:
                self.check_failed.emit(
                    "Yeni sürüm bulundu ama manifest eksik (url/sha256)."
                )
                return

            self.update_available.emit(remote_version, url, sha256)
        finally:
            reply.deleteLater()

    def download(self, url: str, expected_sha256: str, dest_dir: Path) -> None:
        if self._download_reply is not None:
            return

        expected_sha256 = expected_sha256.strip().lower()
        if not expected_sha256:
            raise ValueError("expected_sha256 boş olamaz.")

        dest_dir.mkdir(parents=True, exist_ok=True)
        self._download_dest = dest_dir / "KeepAwakeUpdate.exe"
        self._download_expected_sha256 = expected_sha256

        request = QNetworkRequest(QUrl(url))
        _enable_redirects(request)
        self._download_reply = self.manager.get(request)
        self._download_reply.finished.connect(self._on_download_finished)

    def _on_download_finished(self) -> None:
        reply = self._download_reply
        self._download_reply = None
        if reply is None:
            return

        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.download_finished.emit(False, reply.errorString())
                return

            payload = bytes(reply.readAll())
            digest = hashlib.sha256(payload).hexdigest()

            if digest != self._download_expected_sha256:
                self.download_finished.emit(
                    False, "SHA256 doğrulaması başarısız oldu."
                )
                return

            assert self._download_dest is not None
            self._download_dest.write_bytes(payload)
            self.download_finished.emit(True, str(self._download_dest))
        finally:
            reply.deleteLater()


def run_silent_install(installer_path: str) -> subprocess.Popen:
    """Installer'ı sessiz modda başlatır. Çağıran taraf hemen ardından
    uygulamayı kapatmalıdır ki dosya kilitleri Setup'ı engellemesin."""
    return subprocess.Popen(
        [
            installer_path,
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
        ]
    )
