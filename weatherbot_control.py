#!/usr/bin/env python3
"""Tiny Tkinter control panel for the live Peoria Weather Bot."""

import json
import os
import queue
import shlex
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk


REMOTE_HOST = os.getenv("WEATHERBOT_CONTROL_HOST", "thejasonhowell@jowell-ideapad")
REMOTE_DIR = os.getenv(
    "WEATHERBOT_CONTROL_REMOTE_DIR",
    "/home/thejasonhowell/Documents/Coding/PeoriaWeatherBot",
)
REMOTE_PYTHON = os.getenv(
    "WEATHERBOT_CONTROL_REMOTE_PYTHON",
    "/home/thejasonhowell/Documents/Coding/PeoriaWeatherBot/.venv-linux/bin/python",
)
REMOTE_MAIN = os.getenv(
    "WEATHERBOT_CONTROL_REMOTE_MAIN",
    "/home/thejasonhowell/Documents/Coding/PeoriaWeatherBot/main.py",
)
REMOTE_LOG = os.getenv("WEATHERBOT_CONTROL_REMOTE_LOG", "/tmp/weather.log")
CONTROL_FILE = os.getenv("WEATHERBOT_CONTROL_FILE", "control_command.json")

SSH_OPTIONS = [
    "-o",
    "ConnectTimeout=8",
    "-o",
    "StrictHostKeyChecking=accept-new",
]

CONTROL_COMMANDS = [
    ("Force weather post", "weather"),
    ("Check NWS alerts", "alerts"),
    ("Check SPC outlooks", "spc"),
    ("Check AFD/HWO/LSR/SPC MD", "products"),
    ("Check river/flood", "river"),
    ("Check earthquakes", "earthquakes"),
    ("Send daily summary", "summary"),
    ("Send heartbeat", "heartbeat"),
    ("Run all non-routine checks", "all"),
]


class WeatherBotControl(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Peoria Weather Bot Control")
        self.geometry("780x620")
        self.minsize(640, 520)
        self.output_queue = queue.Queue()

        self.status_var = tk.StringVar(value="Ready")
        self._build_ui()
        self.after(100, self._drain_output_queue)
        self.refresh_status()

    def _build_ui(self):
        shell = ttk.Frame(self, padding=14)
        shell.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(shell, text="Peoria Weather Bot Control", font=("Helvetica", 20, "bold"))
        title.pack(anchor=tk.W)

        subtitle = ttk.Label(
            shell,
            text=f"Target: {REMOTE_HOST}  |  {REMOTE_MAIN}",
            foreground="#555",
        )
        subtitle.pack(anchor=tk.W, pady=(2, 12))

        button_frame = ttk.Frame(shell)
        button_frame.pack(fill=tk.X)

        for index, (label, command) in enumerate(CONTROL_COMMANDS):
            button = ttk.Button(
                button_frame,
                text=label,
                command=lambda selected=command: self.send_control_command(selected),
            )
            button.grid(row=index // 3, column=index % 3, sticky="ew", padx=4, pady=4)

        for column in range(3):
            button_frame.columnconfigure(column, weight=1)

        utility_frame = ttk.Frame(shell)
        utility_frame.pack(fill=tk.X, pady=(10, 8))

        ttk.Button(utility_frame, text="Refresh status + log", command=self.refresh_status).pack(
            side=tk.LEFT,
            padx=(0, 8),
        )
        ttk.Button(utility_frame, text="Clear output", command=self.clear_output).pack(side=tk.LEFT)
        ttk.Label(utility_frame, textvariable=self.status_var).pack(side=tk.RIGHT)

        self.output = scrolledtext.ScrolledText(shell, wrap=tk.WORD, height=24)
        self.output.pack(fill=tk.BOTH, expand=True)
        self.output.configure(font=("Menlo", 12))

    def clear_output(self):
        self.output.delete("1.0", tk.END)

    def refresh_status(self):
        command = (
            f"ps aux | grep {shlex.quote(REMOTE_MAIN)} | grep -v grep; "
            "echo ---LOG---; "
            f"tail -n 80 {shlex.quote(REMOTE_LOG)}"
        )
        self._run_background("Refreshing status and log...", self._ssh_command(command))

    def send_control_command(self, command: str):
        self._run_background(
            f"Sending control command: {command}",
            lambda: self._send_control_command(command),
        )

    def _send_control_command(self, command: str) -> str:
        payload = {
            "command": command,
            "requested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source": "weatherbot_control.py",
        }

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as file:
            json.dump(payload, file)
            temp_path = file.name

        try:
            remote_control_path = f"{REMOTE_DIR}/{CONTROL_FILE}"
            scp_result = self._run_process(
                ["scp", *SSH_OPTIONS, temp_path, f"{REMOTE_HOST}:{remote_control_path}"],
                timeout=20,
            )
            if scp_result.returncode != 0:
                return self._format_result("scp control command", scp_result)

            remote_command = (
                f"cd {shlex.quote(REMOTE_DIR)}; "
                f"pid=$(pgrep -f {shlex.quote('^' + REMOTE_PYTHON + ' ' + REMOTE_MAIN + '$')} | head -n 1); "
                "if [ -z \"$pid\" ]; then echo 'Weather bot process not found.'; exit 1; fi; "
                "kill -USR2 \"$pid\"; "
                f"echo 'Sent {command} to weather bot PID' \"$pid\"; "
                f"tail -n 30 {shlex.quote(REMOTE_LOG)}"
            )
            return self._format_result(
                f"control command {command}",
                self._ssh_command(remote_command)(),
            )
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def _ssh_command(self, remote_command: str):
        return lambda: self._run_process(["ssh", *SSH_OPTIONS, REMOTE_HOST, remote_command], timeout=30)

    def _run_process(self, args: list[str], timeout: int) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)

    def _run_background(self, status: str, work):
        self.status_var.set(status)
        self._append(f"\n== {status} ==\n")

        def runner():
            try:
                result = work()
                if isinstance(result, subprocess.CompletedProcess):
                    message = self._format_result(status, result)
                else:
                    message = str(result)
            except subprocess.TimeoutExpired as exc:
                message = f"Timed out: {exc}\n"
            except Exception as exc:
                message = f"Error: {exc}\n"
            self.output_queue.put(message)
            self.output_queue.put("__READY__")

        threading.Thread(target=runner, daemon=True).start()

    def _format_result(self, label: str, result: subprocess.CompletedProcess) -> str:
        pieces = [f"$ {label}\nexit={result.returncode}\n"]
        if result.stdout:
            pieces.append(result.stdout)
        if result.stderr:
            pieces.append("\nSTDERR:\n")
            pieces.append(result.stderr)
        return "".join(pieces)

    def _drain_output_queue(self):
        while True:
            try:
                message = self.output_queue.get_nowait()
            except queue.Empty:
                break

            if message == "__READY__":
                self.status_var.set("Ready")
            else:
                self._append(message)

        self.after(100, self._drain_output_queue)

    def _append(self, text: str):
        self.output.insert(tk.END, text)
        self.output.see(tk.END)


if __name__ == "__main__":
    WeatherBotControl().mainloop()
