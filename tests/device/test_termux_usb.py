"""Termux fd acquisition and the multi-fd context manager."""
import os
import threading
import time

import pytest

from wifit3.device import termux_usb


@pytest.fixture(autouse=True)
def _reset_state():
    termux_usb._entries.clear()
    termux_usb._reconciling = False
    termux_usb._next_check = 0.0
    termux_usb._imported_env = False
    yield
    termux_usb._entries.clear()


class _Proc:
    def poll(self):
        return None


def test_list_devices_parses_json(monkeypatch):
    monkeypatch.setattr(termux_usb.subprocess, "check_output",
                        lambda *a, **k: '["/dev/bus/usb/001/002"]')
    assert termux_usb.list_devices() == ["/dev/bus/usb/001/002"]


def test_list_devices_empty_on_failure(monkeypatch):
    def boom(*a, **k):
        raise OSError("no termux-usb")

    monkeypatch.setattr(termux_usb.subprocess, "check_output", boom)
    assert termux_usb.list_devices() == []
    assert termux_usb._list_raw() is None


def test_fd_hung_up_detects_closed_fd():
    read_fd, write_fd = os.pipe()
    assert not termux_usb.fd_hung_up(read_fd)
    os.close(read_fd)
    assert termux_usb.fd_hung_up(read_fd)
    os.close(write_fd)


def test_send_and_receive_fd(tmp_path, monkeypatch):
    read_fd, write_fd = os.pipe()
    sock_path = str(tmp_path / "usb.sock")
    result = {}

    def receive():
        result["fd"] = termux_usb._recv_fd(sock_path, _Proc(), timeout=5)

    thread = threading.Thread(target=receive)
    thread.start()
    deadline = time.monotonic() + 5
    while not os.path.exists(sock_path) and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)

    monkeypatch.setenv("TERMUX_USB_FD", str(read_fd))
    termux_usb.send_fd(sock_path)
    thread.join(5)

    received = result.get("fd")
    assert received is not None
    os.write(write_fd, b"hi")
    assert os.read(received, 2) == b"hi"

    os.close(received)
    os.close(read_fd)
    os.close(write_fd)


def test_import_env_fd(monkeypatch):
    read_fd, write_fd = os.pipe()
    monkeypatch.setenv("TERMUX_USB_FD", str(read_fd))
    monkeypatch.setattr(termux_usb, "new_backend", lambda fd: f"ctx{fd}")
    monkeypatch.setattr(termux_usb, "_maybe_reconcile", lambda: None)

    assert termux_usb._backends() == [f"ctx{read_fd}"]
    assert len(termux_usb._entries) == 1

    os.close(read_fd)
    os.close(write_fd)


def test_drops_dead_entry(monkeypatch):
    read_fd, write_fd = os.pipe()
    termux_usb._entries["/dev/bus/usb/001/002"] = termux_usb._Entry(
        "/dev/bus/usb/001/002", read_fd, "ctx")
    monkeypatch.setattr(termux_usb, "_maybe_reconcile", lambda: None)

    os.close(read_fd)
    assert termux_usb._backends() == []
    assert not termux_usb._entries

    os.close(write_fd)


def test_reconcile_adds_and_removes(monkeypatch):
    termux_usb._reconciling = True
    termux_usb._entries["/dev/old"] = termux_usb._Entry("/dev/old", 99999, "old")
    monkeypatch.setattr(termux_usb, "_list_raw", lambda: ["/dev/new"])
    monkeypatch.setattr(termux_usb, "acquire", lambda path: 9)
    monkeypatch.setattr(termux_usb, "new_backend", lambda fd: f"ctx{fd}")
    monkeypatch.setattr(termux_usb, "fd_hung_up", lambda fd: False)
    monkeypatch.setattr(termux_usb, "_close_entry", lambda entry: None)

    termux_usb._reconcile()

    assert set(termux_usb._entries) == {"/dev/new"}
    assert termux_usb._entries["/dev/new"].fd == 9
    assert not termux_usb._reconciling


def test_enumerate_concatenates_contexts(monkeypatch):
    monkeypatch.setattr(termux_usb, "_backends", lambda: ["a", "b"])

    def find(**kw):
        return [kw["backend"], kw["backend"] + "2"]

    monkeypatch.setattr(termux_usb.usb.core, "find", find)
    assert termux_usb.enumerate_devices() == ["a", "a2", "b", "b2"]


def test_find_device_searches_contexts(monkeypatch):
    monkeypatch.setattr(termux_usb, "_backends", lambda: ["a", "b"])
    calls = []

    def find(**kw):
        calls.append(kw)
        return "dev" if kw["backend"] == "b" else None

    monkeypatch.setattr(termux_usb.usb.core, "find", find)
    assert termux_usb.find_device(0x1111, 0x2222, bus=1, address=2) == "dev"
    assert [c["backend"] for c in calls] == ["a", "b"]
    assert calls[0]["bus"] == 1 and calls[0]["address"] == 2


def test_find_all_devices(monkeypatch):
    monkeypatch.setattr(termux_usb, "_backends", lambda: ["a", "b"])
    monkeypatch.setattr(termux_usb.usb.core, "find", lambda **kw: [kw["backend"]])
    assert termux_usb.find_all_devices(1, 2) == ["a", "b"]
