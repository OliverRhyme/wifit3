"""Termux/Android setup: Android grants USB access through the launcher's ``termux-usb`` prompt."""
from __future__ import annotations

from wifit3.models import DeviceID
from wifit3.setup.base import Prompter, Setup, SetupResult


class SetupTermux(Setup):
    """No privileged step: the ``termux-usb -r`` permission dialog is the setup."""

    async def install(self, device_id: DeviceID, ui: Prompter) -> DeviceID | None:
        ui.error(
            "USB access",
            "Start wifit3 through the Termux launcher so Android grants USB access:\n\n"
            "  wifit3-termux /dev/bus/usb/001/002\n\n"
            "List attached devices with: termux-usb -l",
        )
        return None

    async def uninstall(self, device_id: DeviceID, ui: Prompter) -> SetupResult:
        return SetupResult(ok=True, message="Android grants USB access per app; nothing to remove.")
