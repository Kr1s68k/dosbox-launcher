from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_SERVER_NAME = "dosbox-launcher-single-instance"
_CONNECT_TIMEOUT_MS = 300


class SingleInstanceGuard(QObject):
    """Ensures only one copy of the app runs at a time. A second launch
    notifies the first (which re-emits `activation_requested` so it can
    raise its window) and then exits."""

    activation_requested = Signal()

    def __init__(self):
        super().__init__()
        self._server: QLocalServer | None = None

    def try_acquire(self) -> bool:
        """True if this process is now the sole/primary instance. False if
        another instance is already running (already notified to raise
        itself - the caller should just exit)."""
        socket = QLocalSocket()
        socket.connectToServer(_SERVER_NAME)
        if socket.waitForConnected(_CONNECT_TIMEOUT_MS):
            socket.write(b"activate")
            socket.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
            socket.disconnectFromServer()
            return False

        # Nobody answered - any leftover socket file is stale (e.g. after a
        # crash), so clear it before taking over as the primary instance.
        QLocalServer.removeServer(_SERVER_NAME)
        self._server = QLocalServer()
        self._server.newConnection.connect(self._on_new_connection)
        self._server.listen(_SERVER_NAME)
        return True

    def _on_new_connection(self) -> None:
        connection = self._server.nextPendingConnection()
        if connection is not None:
            connection.readyRead.connect(lambda: self._handle_message(connection))

    def _handle_message(self, connection) -> None:
        connection.readAll()
        self.activation_requested.emit()
