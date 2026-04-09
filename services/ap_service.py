from typing import Dict, List, Tuple

from .runtime_service import run_command, which


class APService:
    def __init__(
        self,
        enabled: bool = True,
        interface: str = "auto",
        ssid: str = "FileManager-AP",
        password: str = "ChangeMe123",
    ) -> None:
        self.enabled = enabled
        self.interface = interface
        self.default_ssid = ssid
        self.default_password = password
        self.last_connection_name = ""

    def _resolve_interface(self) -> Tuple[bool, str]:
        if self.interface and self.interface != "auto":
            return True, self.interface

        status = run_command(["nmcli", "-t", "-f", "DEVICE,TYPE", "device", "status"])
        if not status.ok:
            return False, "Wi-Fi arayüzü algılanamadı."

        for line in status.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1] == "wifi":
                return True, parts[0]

        return False, "Uygun Wi-Fi arayüzü bulunamadı."

    def start(self, ssid: str = "", password: str = "") -> Tuple[bool, str]:
        if not self.enabled:
            return False, "AP özelliği config ile devre dışı."
        if not which("nmcli"):
            return False, "nmcli bulunamadı. NetworkManager gerekli."

        ssid = (ssid or self.default_ssid).strip()
        password = (password or self.default_password).strip()
        if len(password) < 8:
            return False, "AP şifresi en az 8 karakter olmalı."

        ok, iface_or_msg = self._resolve_interface()
        if not ok:
            return False, iface_or_msg

        iface = iface_or_msg
        result = run_command(
            [
                "nmcli",
                "device",
                "wifi",
                "hotspot",
                "ifname",
                iface,
                "ssid",
                ssid,
                "password",
                password,
            ],
            timeout=30,
        )
        if not result.ok:
            return False, result.stderr or result.stdout or "AP başlatılamadı."

        self.last_connection_name = ssid
        return True, f"AP başlatıldı. Arayüz: {iface}, SSID: {ssid}"

    def stop(self) -> Tuple[bool, str]:
        if not which("nmcli"):
            return False, "nmcli bulunamadı."

        active = run_command(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"])
        if not active.ok:
            return False, active.stderr or "Aktif bağlantılar okunamadı."

        stopped = 0
        for line in active.stdout.splitlines():
            parts = line.split(":")
            if len(parts) < 2:
                continue
            name, conn_type = parts[0], parts[1]
            if conn_type != "wifi":
                continue
            down = run_command(["nmcli", "connection", "down", name])
            if down.ok:
                stopped += 1

        if stopped == 0:
            return True, "Durdurulacak aktif Wi-Fi AP bağlantısı bulunamadı."
        return True, f"{stopped} bağlantı kapatıldı."

    def status(self) -> Dict[str, object]:
        nmcli_exists = bool(which("nmcli"))
        active_wifi: List[Dict[str, str]] = []

        if nmcli_exists:
            active = run_command(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
            if active.ok:
                for line in active.stdout.splitlines():
                    parts = line.split(":")
                    if len(parts) >= 3 and parts[1] == "wifi":
                        active_wifi.append(
                            {
                                "name": parts[0],
                                "device": parts[2],
                            }
                        )

        return {
            "enabled": self.enabled,
            "nmcli_exists": nmcli_exists,
            "interface": self.interface,
            "active_wifi": active_wifi,
        }

    def clients(self) -> Tuple[bool, List[str], str]:
        if not which("iw"):
            return False, [], "iw komutu bulunamadı."

        ok, iface_or_msg = self._resolve_interface()
        if not ok:
            return False, [], iface_or_msg

        iface = iface_or_msg
        result = run_command(["iw", "dev", iface, "station", "dump"])
        if not result.ok:
            return False, [], result.stderr or "Bağlı istemciler alınamadı."

        clients: List[str] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Station "):
                parts = line.split()
                if len(parts) >= 2:
                    clients.append(parts[1])

        return True, clients, ""
