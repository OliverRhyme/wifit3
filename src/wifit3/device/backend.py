"""The USB backend interface: desktop libusb and Termux's per-fd libusb contexts."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

import usb.core
from usb.backend import IBackend

from wifit3.host import is_termux

logger = logging.getLogger(__name__)

try:
    import libusb_package
except ImportError:
    libusb_package = None

_backend_factory: Optional[Callable[[], "UsbBackend"]] = None


class UsbBackend(ABC):
    """Enumerate and locate USB devices for one transport."""

    @abstractmethod
    def enumerate(self) -> List[usb.core.Device]:
        """Every device the transport currently exposes."""

    @abstractmethod
    def find(self, vid: int, pid: int, bus: Optional[int] = None,
             address: Optional[int] = None) -> Optional[usb.core.Device]:
        """One matching device, or None. A (bus, address) pair selects an exact instance."""

    @abstractmethod
    def find_all(self, vid: int, pid: int) -> List[usb.core.Device]:
        """Every device with this VID:PID."""

    def node_path(self, dev: usb.core.Device) -> Optional[str]:
        """The usbfs node for ``dev`` where the transport has one (desktop Linux)."""
        return None

    def status_hint(self) -> Optional[str]:
        """A short platform error for the UI, or None when there is nothing to report."""
        return None


class LibusbBackend(UsbBackend):
    """Desktop: one libusb context, either bundled or system-provided."""

    def __init__(self, libusb: IBackend) -> None:
        self._libusb = libusb

    def enumerate(self) -> List[usb.core.Device]:
        return list(usb.core.find(find_all=True, backend=self._libusb) or [])

    def find(self, vid: int, pid: int, bus: Optional[int] = None,
             address: Optional[int] = None) -> Optional[usb.core.Device]:
        extra = {"bus": bus, "address": address} if bus is not None and address is not None else {}
        return usb.core.find(idVendor=vid, idProduct=pid, backend=self._libusb, **extra)

    def find_all(self, vid: int, pid: int) -> List[usb.core.Device]:
        return list(usb.core.find(find_all=True, idVendor=vid, idProduct=pid,
                                  backend=self._libusb) or [])

    def node_path(self, dev: usb.core.Device) -> Optional[str]:
        bus, address = getattr(dev, "bus", None), getattr(dev, "address", None)
        if bus is None or address is None:
            return None
        return f"/dev/bus/usb/{bus:03d}/{address:03d}"


class TermuxBackend(UsbBackend):
    """Android: every granted fd owns a libusb context; results are aggregated."""

    def enumerate(self) -> List[usb.core.Device]:
        from wifit3.device import termux_usb
        return termux_usb.enumerate_devices()

    def find(self, vid: int, pid: int, bus: Optional[int] = None,
             address: Optional[int] = None) -> Optional[usb.core.Device]:
        from wifit3.device import termux_usb
        return termux_usb.find_device(vid, pid, bus, address)

    def find_all(self, vid: int, pid: int) -> List[usb.core.Device]:
        from wifit3.device import termux_usb
        return termux_usb.find_all_devices(vid, pid)

    def status_hint(self) -> Optional[str]:
        from wifit3.device import termux_usb
        return termux_usb.last_error()


def set_usb_backend_factory(factory: Optional[Callable[[], UsbBackend]]) -> None:
    """Override the backend factory, e.g. for an alternative USB transport."""
    global _backend_factory
    _backend_factory = factory


def usb_backend() -> UsbBackend:
    """The USB backend. Raises ``usb.core.NoBackendError`` when libusb cannot be loaded."""
    if _backend_factory is not None:
        return _backend_factory()
    if is_termux():
        return TermuxBackend()
    low_level = _desktop_libusb()
    if low_level is None:
        raise usb.core.NoBackendError("No backend available")
    return LibusbBackend(low_level)


def _desktop_libusb() -> Optional[IBackend]:
    if libusb_package is not None:
        backend = libusb_package.get_libusb1_backend()
        if backend is not None:
            return backend
    from usb.backend import libusb1
    backend = libusb1.get_backend()
    if backend is None:
        logger.error("system libusb not found")
    return backend
