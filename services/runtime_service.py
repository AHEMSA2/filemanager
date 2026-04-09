import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int


def which(command: str) -> str:
    return shutil.which(command) or ""


def run_command(cmd: List[str], timeout: int = 20, cwd: Optional[str] = None) -> CommandResult:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=cwd,
        )
        return CommandResult(
            ok=completed.returncode == 0,
            stdout=(completed.stdout or "").strip(),
            stderr=(completed.stderr or "").strip(),
            returncode=completed.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            ok=False,
            stdout=(exc.stdout or "").strip() if exc.stdout else "",
            stderr="Komut zaman aşımına uğradı.",
            returncode=-1,
        )
    except Exception as exc:
        return CommandResult(ok=False, stdout="", stderr=str(exc), returncode=-1)
