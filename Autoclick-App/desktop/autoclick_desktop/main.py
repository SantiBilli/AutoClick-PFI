import os
import multiprocessing
from pathlib import Path
import socket
import sys
from contextlib import nullcontext
from tempfile import TemporaryDirectory
import time

import webview

from autoclick_desktop.api import DesktopApi
from autoclick_desktop.dpi import enable_windows_dpi_awareness
from autoclick_desktop.frontend_server import FrontendServerError, serve_frontend


def is_dev_server_running(host: str = "127.0.0.1", port: int = 5173) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def frontend_url() -> str:
    development_url = os.getenv("AUTOCLICK_DEV_URL") if not getattr(sys, "frozen", False) else None
    if development_url:
        return development_url
    if not getattr(sys, "frozen", False) and is_dev_server_running():
        return "http://127.0.0.1:5173"

    resource_root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    index_file = resource_root / "frontend" / "dist" / "index.html"
    if not index_file.exists():
        raise RuntimeError("No se encontró frontend/dist/index.html; ejecute el build del frontend")
    return str(index_file)


def webview_storage_path() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("No se encontró el directorio LOCALAPPDATA de Windows")
    return Path(local_app_data) / "AutoClick" / "WebView"


def handle_window_closing(api: DesktopApi, timeout: float = 10.0) -> bool:
    """Return False to veto closing while cooperative cleanup is incomplete."""
    return api._cancel_active_for_close(timeout)


def run(*, smoke_test: bool = False) -> int:
    enable_windows_dpi_awareness()
    api = DesktopApi()
    url = frontend_url()
    is_dev = not getattr(sys, "frozen", False) and (
        bool(os.getenv("AUTOCLICK_DEV_URL"))
        or url.startswith("http://127.0.0.1:5173")
        or bool(os.getenv("AUTOCLICK_DEBUG"))
    )
    profile = TemporaryDirectory(prefix="autoclick-smoke-", ignore_cleanup_errors=True) if smoke_test else nullcontext(str(webview_storage_path()))
    rendered = False

    def check_render(window):
        nonlocal rendered
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                rendered = bool(window.evaluate_js(
                    """Boolean(document.querySelector('#root input[type="password"]')
                       && window.pywebview && window.pywebview.api)"""
                ))
                if rendered:
                    break
            except Exception:
                pass  # The document and bridge may still be loading.
            time.sleep(0.2)
        window.destroy()

    with profile as storage, serve_frontend(url, port=0 if smoke_test else 5180) as served_url:
        window = webview.create_window(
            "AutoClick",
            served_url,
            js_api=api,
            width=1440,
            height=900,
            min_size=(1100, 700),
            hidden=smoke_test,
        )
        api._attach_window(window)
        window.events.closing += lambda: handle_window_closing(api)
        options = dict(debug=is_dev, private_mode=smoke_test, storage_path=storage, http_server=False)
        if smoke_test:
            webview.start(check_render, window, **options)
        else:
            webview.start(**options)
    return 0 if not smoke_test or rendered else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if "--check-installation" in sys.argv:
        from autoclick_desktop.action_registry import load_action_registry
        load_action_registry()
        packaged_root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
        if not (packaged_root / "frontend" / "dist" / "index.html").is_file():
            raise RuntimeError("Missing packaged frontend")
    else:
        try:
            sys.exit(run(smoke_test="--smoke-test" in sys.argv))
        except FrontendServerError as error:
            if "--smoke-test" not in sys.argv:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, str(error), "AutoClick", 0x10)
            sys.exit(1)
