import os
import shutil
import threading
import time
from datetime import datetime
from typing import Dict, List, Tuple

import psutil


class USBService:
    def __init__(self, backup_root: str, auto_enabled: bool = True) -> None:
        self.backup_root = backup_root
        os.makedirs(self.backup_root, exist_ok=True)

        self.auto_enabled = auto_enabled
        self._monitor_thread = None
        self._stop_event = threading.Event()

        self._lock = threading.Lock()
        self._active_jobs: Dict[str, str] = {}
        self._completed_devices = set()
        self._last_error = ""

    def list_mounts(self) -> List[Dict[str, str]]:
        devices: List[Dict[str, str]] = []
        for part in psutil.disk_partitions(all=False):
            if "loop" in part.device or part.fstype == "squashfs":
                continue

            mount = part.mountpoint or ""
            if not (
                mount.startswith("/media")
                or mount.startswith("/run/media")
                or mount.startswith("/mnt")
            ):
                continue

            devices.append(
                {
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                }
            )
        return devices

    def _copy_tree_safe(self, source: str, target: str) -> List[str]:
        errors: List[str] = []
        os.makedirs(target, exist_ok=True)

        for item in os.listdir(source):
            src_item = os.path.join(source, item)
            dst_item = os.path.join(target, item)
            try:
                if os.path.isdir(src_item):
                    errors.extend(self._copy_tree_safe(src_item, dst_item))
                else:
                    shutil.copy2(src_item, dst_item)
            except Exception as exc:
                errors.append(f"{src_item} -> {exc}")
        return errors

    def _copy_worker(self, mountpoint: str, job_target: str, device_id: str) -> None:
        try:
            errors = self._copy_tree_safe(mountpoint, job_target)
            if errors:
                self._last_error = "; ".join(errors[:5])
            with self._lock:
                self._completed_devices.add(device_id)
        except Exception as exc:
            self._last_error = str(exc)
        finally:
            with self._lock:
                self._active_jobs.pop(device_id, None)

    def trigger_copy(self, mountpoint: str) -> Tuple[bool, str]:
        if not os.path.isdir(mountpoint):
            return False, f"Geçersiz mountpoint: {mountpoint}"

        device_id = mountpoint
        with self._lock:
            if device_id in self._active_jobs:
                return False, "Bu USB için zaten kopyalama sürüyor."

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            label = os.path.basename(mountpoint.rstrip("/")) or "usb"
            target = os.path.join(self.backup_root, f"USB_{label}_{stamp}")
            self._active_jobs[device_id] = target

        worker = threading.Thread(
            target=self._copy_worker,
            args=(mountpoint, target, device_id),
            daemon=True,
        )
        worker.start()
        return True, f"Kopyalama başladı: {mountpoint} -> {target}"

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            current_mounts = self.list_mounts()
            current_ids = {dev["mountpoint"] for dev in current_mounts}

            if self.auto_enabled:
                for dev in current_mounts:
                    device_id = dev["mountpoint"]
                    with self._lock:
                        should_skip = (
                            device_id in self._completed_devices
                            or device_id in self._active_jobs
                        )
                    if not should_skip:
                        self.trigger_copy(device_id)

            with self._lock:
                removable_done = [d for d in self._completed_devices if d not in current_ids]
                for dev_id in removable_done:
                    self._completed_devices.discard(dev_id)

            time.sleep(2)

    def start_auto_monitor(self) -> Tuple[bool, str]:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return True, "USB izleyici zaten çalışıyor."

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        return True, "USB izleyici başlatıldı."

    def stop_auto_monitor(self) -> Tuple[bool, str]:
        self._stop_event.set()
        return True, "USB izleyici durduruldu."

    def set_auto_enabled(self, enabled: bool) -> Tuple[bool, str]:
        self.auto_enabled = enabled
        status = "açık" if enabled else "kapalı"
        return True, f"USB otomatik kopyalama {status}."

    def get_status(self) -> Dict[str, object]:
        with self._lock:
            active_jobs = dict(self._active_jobs)
            completed = list(self._completed_devices)

        return {
            "auto_enabled": self.auto_enabled,
            "monitor_running": bool(self._monitor_thread and self._monitor_thread.is_alive()),
            "active_jobs": active_jobs,
            "completed_devices": completed,
            "last_error": self._last_error,
            "backup_root": self.backup_root,
        }
