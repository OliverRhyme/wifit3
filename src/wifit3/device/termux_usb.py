"""Android USB file descriptors for Termux.

``termux-usb`` grants a per-device fd inside the Termux:API app, so we receive it over a Unix
socket (both apps share the Termux UID). Each fd gets its own libusb context because the patched
libusb reads ``TERMUX_USB_FD`` only at init. Contexts are aggregated, so multiple cards work and a
replug is just a dropped context plus a fresh one.
"""
from __future__ import annotations

import json
import os
import select
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

import usb.core

LIST_TTL = 2.0
ACQUIRE_TIMEOUT = 120.0

_lock = threading.Lock()
_entries: dict[str, "_Entry"] = {}
_reconciling = False
_next_check = 0.0
_imported_env = False


@dataclass(frozen=True)
class _Entry:
    path: str
    fd: int
    backend: object


def list_devices() -> list[str]:
    """The usbfs paths Android currently exposes to this app."""
    return _list_raw() or []


def _list_raw() -> list[str] | None:
    try:
        return json.loads(subprocess.check_output(["termux-usb", "-l"], text=True))
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def send_fd(sock_path: str) -> None:
    """Callback mode: forward ``TERMUX_USB_FD`` to the launcher's socket."""
    fd = int(os.environ["TERMUX_USB_FD"])
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(sock_path)
    socket.send_fds(sock, [b"wifit3"], [fd])
    sock.close()


def _recv_fd(sock_path: str, proc: subprocess.Popen, timeout: float) -> int | None:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)
    server.settimeout(1.0)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                conn, _ = server.accept()
                break
            except TimeoutError:
                if proc.poll() is not None or time.monotonic() >= deadline:
                    return None
        try:
            _, fds, _, _ = socket.recv_fds(conn, 1, 1)
        finally:
            conn.close()
        return fds[0] if fds else None
    finally:
        server.close()


def acquire(device: str | None = None) -> int | None:
    """Request ``device`` (or the first attached device) and return its fd, or None."""
    if device is None:
        found = list_devices()
        if not found:
            return None
        device = found[0]

    base = os.environ.get("PREFIX") or os.environ.get("HOME") or "/data/data/com.termux/files/usr"
    sock_path = os.path.join(base, "tmp", f"wifit3-usb-{os.getpid()}-{threading.get_ident()}.sock")
    try:
        os.unlink(sock_path)
    except FileNotFoundError:
        pass

    callback = f"{sys.executable} -m wifit3.device.termux_usb --send-fd {sock_path}"
    proc = subprocess.Popen(["termux-usb", "-r", "-E", "-e", callback, device])
    try:
        return _recv_fd(sock_path, proc, ACQUIRE_TIMEOUT)
    finally:
        proc.wait()
        try:
            os.unlink(sock_path)
        except FileNotFoundError:
            pass


def fd_hung_up(fd: int) -> bool:
    try:
        poller = select.poll()
        poller.register(fd, select.POLLERR | select.POLLHUP | select.POLLNVAL)
        return bool(poller.poll(0))
    except (OSError, ValueError):
        return True


def _env_fd() -> int | None:
    raw = os.environ.get("TERMUX_USB_FD")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _path(fd: int) -> str | None:
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return None


def new_backend(fd: int):
    """A libusb context whose initial scan reads ``fd`` through the temporary env override."""
    from usb.backend import libusb1

    try:
        libusb1.get_backend()
        lib = getattr(libusb1, "_lib", None)
        factory = getattr(libusb1, "_LibUSB", None)
        if lib is None or factory is None:
            return None
        previous = os.environ.get("TERMUX_USB_FD")
        os.environ["TERMUX_USB_FD"] = str(fd)
        try:
            return factory(lib)
        finally:
            if previous is None:
                os.environ.pop("TERMUX_USB_FD", None)
            else:
                os.environ["TERMUX_USB_FD"] = previous
    except Exception:
        return None


def _import_env_fd() -> None:
    global _imported_env
    if _imported_env:
        return
    _imported_env = True
    fd = _env_fd()
    if fd is None or fd_hung_up(fd):
        return
    path = _path(fd)
    if path is None or path in _entries:
        return
    backend = new_backend(fd)
    if backend is not None:
        _entries[path] = _Entry(path, fd, backend)


def _close_entry(entry: _Entry) -> None:
    try:
        os.close(entry.fd)
    except OSError:
        pass


def _reconcile() -> None:
    global _reconciling
    try:
        paths = _list_raw()
        if paths is None:
            return
        with _lock:
            stale = [e for path, e in _entries.items() if path not in paths or fd_hung_up(e.fd)]
            for entry in stale:
                _entries.pop(entry.path, None)
        for entry in stale:
            _close_entry(entry)
        for path in paths:
            with _lock:
                if path in _entries:
                    continue
            fd = acquire(path)
            if fd is None:
                continue
            backend = new_backend(fd)
            if backend is None:
                os.close(fd)
                continue
            with _lock:
                _entries[path] = _Entry(path, fd, backend)
    finally:
        with _lock:
            _reconciling = False


def _maybe_reconcile() -> None:
    global _reconciling, _next_check
    now = time.monotonic()
    if _reconciling or now < _next_check:
        return
    _next_check = now + LIST_TTL
    _reconciling = True
    threading.Thread(target=_reconcile, daemon=True).start()


def _backends() -> list[object]:
    with _lock:
        _import_env_fd()
        dead = [e for e in _entries.values() if fd_hung_up(e.fd)]
        for entry in dead:
            _entries.pop(entry.path, None)
        _maybe_reconcile()
        snapshot = [e.backend for e in _entries.values()]
    for entry in dead:
        _close_entry(entry)
    return snapshot


def enumerate_devices() -> list[usb.core.Device]:
    """Every device across all granted Android fds."""
    out: list[usb.core.Device] = []
    for backend in _backends():
        try:
            out.extend(usb.core.find(find_all=True, backend=backend) or [])
        except Exception:
            continue
    return out


def find_device(vid: int, pid: int, bus: int | None = None,
                address: int | None = None) -> usb.core.Device | None:
    """The first matching device across all granted Android fds."""
    for backend in _backends():
        extra = {"bus": bus, "address": address} if bus is not None and address is not None else {}
        try:
            dev = usb.core.find(idVendor=vid, idProduct=pid, backend=backend, **extra)
        except Exception:
            continue
        if dev is not None:
            return dev
    return None


def find_all_devices(vid: int, pid: int) -> list[usb.core.Device]:
    """Every device with this VID:PID across all granted Android fds."""
    out: list[usb.core.Device] = []
    for backend in _backends():
        try:
            out.extend(usb.core.find(find_all=True, idVendor=vid, idProduct=pid,
                                     backend=backend) or [])
        except Exception:
            continue
    return out


if __name__ == "__main__":
    if sys.argv[1:2] == ["--send-fd"]:
        send_fd(sys.argv[2])
    else:
        print("usage: python -m wifit3.device.termux_usb --send-fd SOCKET", file=sys.stderr)
        sys.exit(2)
