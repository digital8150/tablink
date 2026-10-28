"""adb device discovery: USB + wireless debugging (mDNS), grouped by physical device."""
import re

from scrcpy_ctrl import adb


class Transport:
    def __init__(self, serial, state, model, wireless):
        self.serial = serial
        self.state = state
        self.model = model
        self.wireless = wireless
        self.device_id = None  # ro.serialno, identical for USB and Wi-Fi transports

    @property
    def kind(self):
        return "Wi-Fi" if self.wireless else "USB"


_id_cache = {}


def _is_wireless(serial):
    return bool(re.match(r"^\d+\.\d+\.\d+\.\d+:\d+$", serial)) or "._adb-tls-connect." in serial


def list_transports():
    out = adb("devices", "-l", check=False, timeout=10)
    result = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        model = next((p.split(":", 1)[1] for p in parts if p.startswith("model:")), "")
        t = Transport(serial, state, model.replace("_", "-"), _is_wireless(serial))
        if state == "device":
            if serial not in _id_cache:
                try:
                    _id_cache[serial] = adb("-s", serial, "shell", "getprop", "ro.serialno", timeout=5).strip() or serial
                except Exception:
                    _id_cache[serial] = serial
            t.device_id = _id_cache[serial]
        else:
            t.device_id = re.sub(r"^adb-([^-]+)-.*", r"\1", serial)
        result.append(t)
    return result


def mdns_endpoints():
    """Wireless-debugging endpoints advertised on the LAN: [(device_id, 'ip:port')]."""
    out = adb("mdns", "services", check=False, timeout=8)
    found = []
    for line in out.splitlines():
        m = re.match(r"^adb-(\S+?)-\S*\s+_adb-tls-connect\._tcp\.?\s+(\d+\.\d+\.\d+\.\d+:\d+)", line.strip())
        if m:
            found.append((m.group(1), m.group(2)))
    return found


def connect(endpoint):
    out = adb("connect", endpoint, check=False, timeout=10)
    return "connected" in out and "cannot" not in out and "failed" not in out, out.strip()


def pair(endpoint, code):
    out = adb("pair", endpoint, code, check=False, timeout=20)
    return "Successfully paired" in out, out.strip()


def disconnect(serial):
    adb("disconnect", serial, check=False, timeout=5)
