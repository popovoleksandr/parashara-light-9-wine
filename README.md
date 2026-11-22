# parashara-light-9-wine

Run **Parashara's Light 9** (GeoVision, build B5) on Linux under Wine, with its
Feitian ROCKEY USB hardware key.

Out of the box the program does not start under Wine, and once it starts it
cannot see the key. This folder holds the three small fixes that make it work
and a launcher that keeps them applied.

Tested on Arch Linux (Omarchy), Wine 11.20, kernel 7.2, with the key
`096e:0006` ("OEM HID Dongle").

This is an unofficial compatibility aid. It is not affiliated with or endorsed
by GeoVision Software. It contains no part of Parashara's Light and does not
remove or bypass its licensing: you still need your own installer, your own
hardware key, and a valid activation.

## Requirements

- `wine` (11.x, 64-bit prefix with the new WoW64 mode) and `winetricks`
- `python3` — the helpers use only the standard library
- systemd and udev (for the key bridge)
- The PL9 installer and your hardware key

## Install

The commands below assume the repository is cloned to
`~/Projects/parashara-light-9-wine`:

```bash
git clone https://github.com/popovoleksandr/parashara-light-9-wine.git ~/Projects/parashara-light-9-wine
```

1. Install the program into its own Wine prefix. Copy the installer off any
   network or cloud mount first.

   ```bash
   export WINEPREFIX=~/.local/share/wineprefixes/pl9
   wineboot -u
   winetricks -q corefonts
   wine ~/Downloads/"PL9 Installer.exe"
   ```

   Keep the default install folder (`C:\GeoVision\PL9`).

2. Install the key bridge. This is the only step that needs root.

   ```bash
   sudo ~/Projects/parashara-light-9-wine/install.sh
   ```

3. Put the launcher on your `PATH` and point the app-menu entry at it.

   ```bash
   ln -sf ~/Projects/parashara-light-9-wine/pl9 ~/.local/bin/pl9
   sed -i "s|^Exec=.*|Exec=$HOME/Projects/parashara-light-9-wine/pl9|" \
     ~/.local/share/applications/wine/Programs/"Parashara's Light 9 B5/Parashara's Light 9 B5.desktop"
   ```

4. On a scaled (HiDPI) screen, raise Wine's DPI and turn on font smoothing.
   Without this the menus use a tiny, badly drawn bitmap font. 120 suits a
   125% screen; use 96 × your scale factor.

   ```bash
   export WINEPREFIX=~/.local/share/wineprefixes/pl9
   wine reg add 'HKCU\Control Panel\Desktop' /v LogPixels /t REG_DWORD /d 120 /f
   wine reg add 'HKLM\System\CurrentControlSet\Hardware Profiles\Current\Software\Fonts' /v LogPixels /t REG_DWORD /d 120 /f
   wine reg add 'HKCU\Control Panel\Desktop' /v FontSmoothing /t REG_SZ /d 2 /f
   wine reg add 'HKCU\Control Panel\Desktop' /v FontSmoothingType /t REG_DWORD /d 2 /f
   wine reg add 'HKCU\Control Panel\Desktop' /v FontSmoothingGamma /t REG_DWORD /d 1400 /f
   wine reg add 'HKCU\Control Panel\Desktop' /v FontSmoothingOrientation /t REG_DWORD /d 1 /f
   ```

## Use

Plug in the key, then start **Parashara's Light 9 B5** from the app menu or run:

```bash
pl9
```

Always start it through the launcher. Running `wine PL9.exe` directly skips the
fixes below.

The first start shows the "Activate product" dialog. Activation is tied to the
Wine prefix, so keep the prefix rather than recreating it.

## What is in here

| File | What it does |
| --- | --- |
| `pl9` | Launcher. Re-applies the two Wine-side fixes, then starts `PL9.exe`. |
| `fix-wine-bss.py` | Fix 1: patches one header field in the prefix's `user32.dll`. |
| `rockey-hid-bridge.py` | Fix 2: presents the hardware key as a normal HID device. |
| `make-hid-shim.py` | Fix 3: builds an app-local `hid.dll` with a working `HidD_FlushQueue`. |
| `install.sh` | Installs (or removes) the bridge service and udev rule. |

## The three problems and their fixes

### 1. Crash at startup

**Symptom:** `Unhandled page fault on read access to 00000014 at address
029072CD`, before any window appears.

**Cause:** PL9's protection wrapper reads `C:\windows\system32\user32.dll` from
disk and parses it by hand. Wine's DLLs contain an empty `.bss` section whose
`PointerToRawData` is 0. The wrapper mishandles that, wipes its own copy of the
file's headers, and then dereferences a null section pointer.

**Fix:** `fix-wine-bss.py` points the empty section at the next section's file
offset. Wine ignores the field (the section has no file data), and the wrapper's
parser then works. The untouched file is kept beside it as `user32.dll.orig`.
A Wine upgrade rewrites the prefix's DLLs, so the launcher runs the fix on every
start; it does nothing when the file is already patched.

### 2. "Hardware Key not found!" — Wine cannot see the key

**Cause:** The key is a HID-class device with only a control endpoint. The
kernel's `usbhid` driver refuses it (`couldn't find an input interrupt
endpoint`), so no `/dev/hidraw` node exists and Wine has no HID device to offer
the program.

**Fix:** `rockey-hid-bridge.py` creates a virtual HID device through `/dev/uhid`
using the key's own report descriptor, and forwards each feature-report request
to the real key as a USB control transfer. `install.sh` sets up:

- `/usr/local/lib/rockey-hid-bridge.py` — the bridge
- `/etc/systemd/system/rockey-hid-bridge@.service` — one instance per plugged-in key
- `/etc/udev/rules.d/70-rockey-hid-bridge.rules` — starts the service when the
  key is plugged in, and lets the logged-in user open the bridged device

The virtual device must carry the key's exact USB product string
("HID Dongle"). PL9 checks it and ignores the device otherwise.

### 3. "Hardware Key not found!" — key answers but is rejected

**Cause:** After each command PL9 calls `HidD_FlushQueue` and aborts if it
fails. Wine does not implement that call (`IOCTL_HID_FLUSH_QUEUE`).

**Fix:** `make-hid-shim.py` copies Wine's own 32-bit `hid.dll` into the PL9
folder, makes `HidD_FlushQueue` return TRUE (the key has no input queue to
flush), and removes the "Wine builtin" marker so Wine loads the local copy. The
launcher sets `WINEDLLOVERRIDES=hid=n,b` and rebuilds the copy whenever Wine's
`hid.dll` is newer.

## Troubleshooting

Check that the bridge is running and the key is visible:

```bash
systemctl status 'rockey-hid-bridge@*'
grep -l 096E /sys/class/hidraw/*/device/uevent
```

Run with Wine's log output to see what the program is doing:

```bash
WINEDEBUG=err+all,+msgbox pl9
```

| Symptom | Likely cause |
| --- | --- |
| Page fault at `029072CD` again | Started without the launcher, or `user32.dll` was replaced and not re-patched. |
| "Hardware Key not found!" | Key unplugged, bridge service not running, or `hid.dll` missing from the PL9 folder. |
| Bridge service fails right after plugging in | See `journalctl -u 'rockey-hid-bridge@*'`. |

If the key was plugged in before the bridge was installed, re-plug it or run
`install.sh` again; it starts the bridge for keys that are already present.

## Uninstall

```bash
sudo ~/Projects/parashara-light-9-wine/install.sh --uninstall   # bridge service and udev rule
rm ~/.local/bin/pl9
rm -rf ~/.local/share/wineprefixes/pl9            # the program and its activation
```

## Limits

- Verified only as far as the program starting, talking to the key, and opening
  its windows. Charts, printing and fonts have not been checked.
- The fixes are tied to how Wine 11.20 builds its DLLs. A future Wine may not
  need fix 1 or fix 3, or may need them adjusted.
- The bridge handles the `096e:0006` key only. Other ROCKEY models use
  different IDs and may behave differently.
- Fix 3 patches 32-bit x86 code, so it applies to the 32-bit `hid.dll` only.

## License

MIT — see [LICENSE](LICENSE).

Parashara's Light is a trademark of its owner. The app-local `hid.dll` is
generated on your machine from your own Wine installation (LGPL) and is not
distributed here.
