"""Own the packaged UI listener before opening a WebView."""
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from threading import Thread


class FrontendServerError(RuntimeError):
    pass


class FrontendServer(ThreadingHTTPServer):
    # Windows must reject a second listener rather than sharing its address.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class FrontendHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format, *args):
        pass


@contextmanager
def serve_frontend(location: str, *, port: int = 5180):
    if location.startswith(("http://", "https://")):
        # Vite already serves development assets. It must not occupy the EXE port.
        yield location
        return

    index = Path(location).resolve(strict=True)
    handler = partial(FrontendHandler, directory=str(index.parent))
    try:
        server = FrontendServer(("127.0.0.1", port), handler)
    except OSError as error:
        raise FrontendServerError(
            "No se pudo iniciar la interfaz de AutoClick porque su conexión local "
            "está ocupada o no está disponible. Cerrá las otras ventanas de AutoClick "
            "y volvé a abrirlo."
        ) from error
    worker = Thread(target=server.serve_forever, daemon=True, name="autoclick-frontend")
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/{index.name}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
