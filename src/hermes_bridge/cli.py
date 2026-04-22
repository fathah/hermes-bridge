from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


async def run_hermes_cli(
    args: list[str],
    *,
    container_name: str,
    timeout: float = 30.0,
) -> CommandResult:
    """Invoke `hermes ...` inside the hermes container via `docker exec`.

    See PLAN §14 option A. Requires the docker socket mounted into the
    bridge container.
    """
    cmd = ["docker", "exec", container_name, "hermes", *args]
    return await _run(cmd, timeout=timeout)


async def _run(cmd: list[str], *, timeout: float) -> CommandResult:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return CommandResult(returncode=124, stdout="", stderr=f"timeout after {timeout}s")
    return CommandResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout_b.decode("utf-8", errors="replace"),
        stderr=stderr_b.decode("utf-8", errors="replace"),
    )
