import time
from typing import Dict, List, Tuple

from .runtime_service import run_command


class PowerService:
    def __init__(self, min_seconds: int = 0, max_seconds: int = 86400) -> None:
        self.min_seconds = min_seconds
        self.max_seconds = max_seconds
        self._scheduled_units: List[str] = []

    def _validate_seconds(self, seconds: int) -> Tuple[bool, str]:
        if seconds < self.min_seconds or seconds > self.max_seconds:
            return (
                False,
                f"Süre {self.min_seconds}-{self.max_seconds} aralığında olmalı.",
            )
        return True, ""

    def _schedule(self, action: str, seconds: int) -> Tuple[bool, str]:
        ok, msg = self._validate_seconds(seconds)
        if not ok:
            return False, msg

        action_cmd = "poweroff" if action == "shutdown" else "reboot"
        unit_name = f"filemanager-{action}-{int(time.time())}"
        result = run_command(
            [
                "systemd-run",
                f"--unit={unit_name}",
                f"--on-active={seconds}s",
                "systemctl",
                action_cmd,
            ]
        )

        if not result.ok:
            err = result.stderr or result.stdout or "Bilinmeyen hata"
            return False, f"İşlem planlanamadı: {err}"

        self._scheduled_units.append(unit_name)
        return True, f"{action} işlemi {seconds} saniye sonra planlandı. Unit: {unit_name}"

    def schedule_shutdown(self, seconds: int) -> Tuple[bool, str]:
        return self._schedule("shutdown", seconds)

    def schedule_reboot(self, seconds: int) -> Tuple[bool, str]:
        return self._schedule("reboot", seconds)

    def cancel_scheduled(self) -> Tuple[bool, str]:
        cancelled = 0
        for unit in list(self._scheduled_units):
            result = run_command(["systemctl", "stop", unit])
            if result.ok:
                cancelled += 1
                self._scheduled_units.remove(unit)

        # shutdown -c varsa onu da deneriz; başarısız olsa da kritik değil.
        run_command(["shutdown", "-c"])

        if cancelled == 0:
            return True, "Aktif planlı power görevi bulunamadı."
        return True, f"{cancelled} planlı görev iptal edildi."

    def status(self) -> Dict[str, object]:
        statuses = []
        for unit in list(self._scheduled_units):
            active = run_command(["systemctl", "is-active", unit])
            is_active = active.ok and (active.stdout.strip() == "active")
            if not is_active:
                self._scheduled_units.remove(unit)
            statuses.append(
                {
                    "unit": unit,
                    "active": is_active,
                }
            )
        return {
            "min_seconds": self.min_seconds,
            "max_seconds": self.max_seconds,
            "scheduled": statuses,
        }
