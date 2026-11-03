# Running wifit3 in Termux (Android)

**Status: experimental.** wifit3 was built for desktop Linux, Windows, and macOS. This port runs the
same Python code natively in Termux, using Android's USB host API through `termux-usb`. There is no
VM, no proot, and no root.

## Requirements

- A rooted-free Android device with USB-OTG support
- Termux and the Termux:API app
- A supported USB adapter (for example the TP-Link Archer T2U+ / RTL8821AU, `2357:0120`)
- A **powered** USB hub or OTG Y-cable; the adapter can draw more current than the phone supplies
- A Termux `libusb` build that understands `TERMUX_USB_FD` (the patch landed in late 2024)

Install the packages:

```bash
pkg install python libusb termux-api git
```

## Install

`libusb-package` (the desktop dependency) bundles a glibc library that cannot load under Termux, so
install wifit3 without its dependencies and supply the pure-Python ones explicitly:

```bash
git clone https://github.com/derv82/wifit3
cd wifit3
pip install --no-deps -e .
pip install platformdirs pyusb rich textual
install -m755 scripts/termux/wifit3-termux "$PREFIX/bin/wifit3-termux"
```

## Run

Android grants USB access per device and per app launch, so start wifit3 through the launcher:

```bash
wifit3-termux                          # auto-picks the first attached device
wifit3-termux /dev/bus/usb/001/002     # or name it explicitly
```

Accept the Android permission dialog when it appears. Tick "Use by default for this USB device" if
Android offers it, so a replug needs no confirmation.

The launcher requests the first device; once wifit3 is running, every other attached adapter is
requested and brought up as well. Each granted fd gets its own libusb context, and the contexts are
aggregated, so the multi-card features work exactly as they do on desktop.

If the adapter is unplugged, wifit3 keeps running. It reports the card as gone, and when the adapter
returns the app re-requests the descriptor and brings the card back up — the same departure/arrival
flow as desktop. Android may ask for USB permission again unless "Use by default for this USB
device" was ticked.

The launcher requests the device with `termux-usb -r -E` and receives the descriptor over a Unix
socket, then execs wifit3 with the terminal and `TERMUX_USB_FD` intact. It cannot simply use
`termux-usb -e "wifit3"`: that callback runs inside the Termux:API app with pipes for stdio, so
Textual sees no terminal and renders at its 80x25 fallback size.

## What differs from desktop Linux

- **No udev, no modprobe.** Android's `UsbHostManager` owns device claiming; the permission dialog is
  the only "setup" step. `SetupTermux` replaces `SetupLinux`.
- **One context per granted fd.** Termux's patched libusb reads `TERMUX_USB_FD` only at init, so each
  adapter gets a fresh context and the contexts are aggregated. Android prompts per adapter unless
  "Use by default for this USB device" is ticked.
- **No kernel driver detach.** wifit3's userland drivers want a cold-boot card. Most stock Android
  kernels ship no `rtw88`/`ath9k_htc` USB drivers, so the dongle stays cold. If your kernel does bind
  one, the port may fail on that ROM.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Splash shows no devices | Launch through `wifit3-termux`; a bare `wifit3` has no USB descriptor. |
| `termux-usb -l` does not list the card | Check OTG support and power; try a powered hub. |
| `system libusb not found` | `pkg install libusb`. |
| Adapter disappears mid-run | Power. Use a powered hub or OTG Y-cable. |
| Driver reports a warm/claimed device | The ROM bound a kernel driver; test on another ROM or use a rooted setup. |

## Notes

- Termux reports `sys.platform == "linux"`, so detection uses `TERMUX_VERSION` (see
  `src/wifit3/host.py`).
- The code changes are `host.py`, `device/backend.py`, `setup/termux.py`, plus backend wiring in
  `device/manager.py`, `__main__.py`, `ui/app.py`, and two chip drivers.
- Upstreaming is not done. This branch is a working starting point, not a supported release.
