"""One managed, headless Vivado Tcl session."""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path

from .protocol import TclResponse, create_request, parse_response


class VivadoSessionError(RuntimeError):
    """Base error for starting or communicating with Vivado."""


class VivadoNotRunningError(VivadoSessionError):
    """Raised when a command is sent without a live process."""


class VivadoCommandTimeout(VivadoSessionError):
    """Raised when Tcl is still running after the caller's time budget."""


class VivadoSessionBusy(VivadoSessionError):
    """Raised when the previous timed-out Tcl command has not completed."""


class VivadoSession:
    """Own exactly one Vivado process and serialize all Tcl calls."""

    def __init__(self, vivado_path: Path) -> None:
        self.vivado_path = vivado_path
        self._process: asyncio.subprocess.Process | None = None
        self._command_lock = asyncio.Lock()
        self._inflight: asyncio.Task[TclResponse] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=100)

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self.is_alive and self._process else None

    @property
    def stderr_tail(self) -> list[str]:
        return list(self._stderr_tail)

    async def start(self) -> bool:
        """Start Vivado in Tcl mode. Return False when it was already alive."""

        if self.is_alive:
            return False
        if not self.vivado_path.is_file():
            raise VivadoSessionError(f"Vivado executable does not exist: {self.vivado_path}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                str(self.vivado_path),
                "-mode",
                "tcl",
                "-nojournal",
                "-nolog",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            self._process = None
            raise VivadoSessionError(f"Failed to start Vivado: {exc}") from exc

        self._stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            probe = await self.execute('puts "VAMCP_READY"', timeout_seconds=45)
        except Exception:
            await self.stop()
            raise
        if not probe.ok or "VAMCP_READY" not in probe.output:
            await self.stop()
            raise VivadoSessionError("Vivado started but did not pass the Tcl readiness probe")
        return True

    async def execute(self, command: str, *, timeout_seconds: float = 30) -> TclResponse:
        """Execute one framed command without allowing response interleaving.

        If a caller times out, the underlying reader stays alive. Until its unique
        end marker arrives the session reports BUSY, protecting later MCP calls
        from consuming stale output.
        """

        async with self._command_lock:
            self._require_process()
            if self._inflight is not None:
                if not self._inflight.done():
                    raise VivadoSessionBusy(
                        "A previous Tcl command is still running; inspect its job before retrying"
                    )
                self._inflight.result()
                self._inflight = None

            request = create_request(command)
            assert self._process is not None and self._process.stdin is not None
            self._process.stdin.write(request.payload.encode("utf-8"))
            await self._process.stdin.drain()
            self._inflight = asyncio.create_task(self._read_response(request))

            try:
                response = await asyncio.wait_for(
                    asyncio.shield(self._inflight), timeout=timeout_seconds
                )
            except TimeoutError as exc:
                raise VivadoCommandTimeout(
                    f"Tcl command exceeded {timeout_seconds:g}s; "
                    "the session remains busy until it ends"
                ) from exc
            else:
                self._inflight = None
                return response

    async def stop(self) -> bool:
        """Stop the owned process. Return False if there was no live process."""

        process = self._process
        if process is None:
            return False

        if self._inflight is not None:
            self._inflight.cancel()
            await asyncio.gather(self._inflight, return_exceptions=True)
            self._inflight = None

        if process.returncode is None:
            try:
                if process.stdin is not None:
                    process.stdin.write(b"exit\n")
                    await process.stdin.drain()
                await asyncio.wait_for(process.wait(), timeout=5)
            except (TimeoutError, BrokenPipeError, ConnectionResetError):
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    process.kill()
                    await process.wait()

        if self._stderr_task is not None:
            self._stderr_task.cancel()
            await asyncio.gather(self._stderr_task, return_exceptions=True)
            self._stderr_task = None
        self._process = None
        return True

    async def _read_response(self, request: object) -> TclResponse:
        from .protocol import TclRequest

        assert isinstance(request, TclRequest)
        self._require_process()
        assert self._process is not None and self._process.stdout is not None
        lines: list[str] = []
        while True:
            raw_line = await self._process.stdout.readline()
            if not raw_line:
                stderr = "\n".join(list(self._stderr_tail)[-10:])
                raise VivadoSessionError(
                    f"Vivado exited before response marker. Recent stderr: {stderr or '(empty)'}"
                )
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line.strip() == request.end_marker:
                return parse_response(request, "\n".join(lines))
            lines.append(line)

    async def _drain_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        while True:
            line = await self._process.stderr.readline()
            if not line:
                return
            self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())

    def _require_process(self) -> None:
        if not self.is_alive:
            raise VivadoNotRunningError("Vivado is not running; call start_vivado first")
