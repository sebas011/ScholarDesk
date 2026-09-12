"""Local Windows control window for a shared ScholarDesk host."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import tkinter as tk
from tkinter import messagebox
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


APPLICATION_EXECUTABLE_NAME = "ScholarDesk.exe"
HOST_CONTROL_TOKEN_ENVIRONMENT = "SCHOLARDESK_HOST_CONTROL_TOKEN"
HOST_CONTROL_TOKEN_HEADER = "X-ScholarDesk-Host-Token"
HOST_SHUTDOWN_URL = "http://127.0.0.1:8000/internal/host-shutdown"
SHUTDOWN_TIMEOUT_SECONDS = 10


def release_directory() -> Path:
    """Return the directory containing the portable release executables."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def application_executable_path(directory: Path) -> Path:
    """Locate the release application beside this host-control executable."""
    return directory / APPLICATION_EXECUTABLE_NAME


def request_graceful_shutdown(token: str) -> None:
    """Request the local server to finish its current request and exit."""
    request = Request(
        HOST_SHUTDOWN_URL,
        method="POST",
        headers={HOST_CONTROL_TOKEN_HEADER: token},
    )
    with urlopen(request, timeout=5) as response:  # noqa: S310 -- fixed loopback URL
        if response.status != 200:
            raise RuntimeError(f"ScholarDesk returned unexpected status {response.status}.")


class HostControlWindow:
    """Own one child ScholarDesk process for the duration of the workday."""

    def __init__(self, root: tk.Tk, directory: Path | None = None) -> None:
        self.root = root
        self.directory = directory or release_directory()
        self.process: subprocess.Popen[Any] | None = None
        self.shutdown_token: str | None = None
        self.close_after_stop = False

        root.title("ScholarDesk Host Control")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        frame = tk.Frame(root, padx=24, pady=20)
        frame.pack()
        tk.Label(frame, text="ScholarDesk Host", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(
            frame,
            text="Keep this window open while coworkers use ScholarDesk on the network.",
            wraplength=360,
            justify="left",
        ).pack(anchor="w", pady=(6, 16))

        self.status = tk.StringVar(value="ScholarDesk is stopped.")
        tk.Label(frame, textvariable=self.status, wraplength=360, justify="left").pack(
            anchor="w", pady=(0, 16)
        )

        buttons = tk.Frame(frame)
        buttons.pack(anchor="w")
        self.start_button = tk.Button(buttons, text="Start ScholarDesk", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = tk.Button(
            buttons, text="Stop ScholarDesk", command=self.stop, state="disabled"
        )
        self.stop_button.pack(side="left", padx=(8, 0))

        self.root.after(500, self.monitor_process)

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if self.is_running():
            return

        executable = application_executable_path(self.directory)
        if not executable.is_file():
            messagebox.showerror(
                "ScholarDesk not found",
                "Keep "
                f"{APPLICATION_EXECUTABLE_NAME} in the same folder as this control utility.\n\n"
                f"Expected: {executable}",
            )
            return

        self.shutdown_token = secrets.token_urlsafe(32)
        environment = os.environ.copy()
        environment[HOST_CONTROL_TOKEN_ENVIRONMENT] = self.shutdown_token
        try:
            self.process = subprocess.Popen(
                [str(executable)], cwd=self.directory, env=environment
            )
        except OSError as error:
            self.process = None
            self.shutdown_token = None
            messagebox.showerror("Could not start ScholarDesk", str(error))
            return

        self.status.set("ScholarDesk is starting. It will open in your default browser.")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def stop(self) -> None:
        if not self.is_running() or self.shutdown_token is None:
            self.mark_stopped("ScholarDesk is stopped.")
            return

        self.stop_button.configure(state="disabled")
        self.status.set("Stopping ScholarDesk safely…")
        try:
            request_graceful_shutdown(self.shutdown_token)
        except (RuntimeError, URLError, TimeoutError) as error:
            self.stop_button.configure(state="normal")
            self.status.set("ScholarDesk is still running.")
            messagebox.showerror("Could not stop ScholarDesk", str(error))
            return

        self.wait_for_shutdown(time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS)

    def wait_for_shutdown(self, deadline: float) -> None:
        if not self.is_running():
            self.mark_stopped("ScholarDesk stopped safely.")
            if self.close_after_stop:
                self.root.destroy()
            return
        if time.monotonic() < deadline:
            self.root.after(200, lambda: self.wait_for_shutdown(deadline))
            return

        self.stop_button.configure(state="normal")
        self.status.set("ScholarDesk did not stop in time; it may still be running.")
        messagebox.showerror(
            "Shutdown delayed",
            "ScholarDesk did not stop within 10 seconds. Wait briefly and try again; "
            "do not force-close it while a coworker may be saving data.",
        )

    def mark_stopped(self, message: str) -> None:
        self.process = None
        self.shutdown_token = None
        self.status.set(message)
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def monitor_process(self) -> None:
        if self.process is not None and self.process.poll() is not None:
            self.mark_stopped("ScholarDesk stopped.")
        self.root.after(500, self.monitor_process)

    def on_close(self) -> None:
        if not self.is_running():
            self.root.destroy()
            return
        should_stop = messagebox.askyesno(
            "Stop ScholarDesk?",
            "ScholarDesk is still available to coworkers. Stop it safely and close "
            "this control window?",
        )
        if should_stop:
            self.close_after_stop = True
            self.stop()


def main() -> None:
    root = tk.Tk()
    HostControlWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
