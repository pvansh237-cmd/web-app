"""
gui_agent.py — Windows desktop app (GUI) version, now using real WebRTC
for a true peer-to-peer connection (fast + stays clear).

Package into .exe with:
    pyinstaller --onefile --windowed --name ScreenShareAgent gui_agent.py
"""

import asyncio
import threading
import tkinter as tk
from tkinter import messagebox

from agent_core import run_agent

SERVER_URL = "wss://screen-project.onrender.com"
VIEWER_LINK = "https://screen-project.onrender.com"


class AgentState:
    def __init__(self):
        self.stop_event = None
        self.loop = None
        self.thread = None


state = AgentState()


def start_agent_thread(on_pin_ready, on_status, on_error, on_stopped):
    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        state.loop = loop
        stop_event = asyncio.Event()
        state.stop_event = stop_event
        try:
            # run_agent only raises if it NEVER managed to connect at all.
            # Once a peer connection is live, it keeps the loop alive on
            # its own until stop_event is set — signaling hiccups won't
            # kill an already-working screen share.
            loop.run_until_complete(run_agent(SERVER_URL, on_pin_ready, on_status, stop_event))
        except Exception as e:
            on_error(str(e))
        finally:
            on_stopped()
            loop.close()

    t = threading.Thread(target=runner, daemon=True)
    state.thread = t
    t.start()


def stop_agent():
    if state.loop and state.stop_event:
        state.loop.call_soon_threadsafe(state.stop_event.set)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Screen Share Agent")
        self.geometry("460x420")
        self.resizable(False, False)
        self.configure(bg="#0f1117")

        tk.Label(self, text="🖥️ Screen Share Agent", font=("Segoe UI", 16, "bold"),
                 fg="#4fd1c5", bg="#0f1117").pack(pady=(20, 4))
        tk.Label(self, text="Direct peer-to-peer — fast & clear.",
                 font=("Segoe UI", 9), fg="#9aa0a6", bg="#0f1117").pack(pady=(0, 16))

        self.status_var = tk.StringVar(value="Not started")
        tk.Label(self, textvariable=self.status_var, font=("Segoe UI", 10),
                 fg="#e6e6e6", bg="#0f1117", wraplength=400).pack(pady=(0, 14))

        self.start_btn = tk.Button(self, text="▶  Start Sharing", font=("Segoe UI", 11, "bold"),
                                    bg="#4fd1c5", fg="#0f1117", relief="flat", padx=16, pady=8,
                                    command=self.on_start)
        self.start_btn.pack(pady=4)

        self.stop_btn = tk.Button(self, text="■  Stop", font=("Segoe UI", 10), bg="#f56565",
                                   fg="white", relief="flat", padx=16, pady=6,
                                   command=self.on_stop, state="disabled")
        self.stop_btn.pack(pady=4)

        self.pin_frame = tk.Frame(self, bg="#1a1d27")
        tk.Label(self.pin_frame, text="PIN", font=("Segoe UI", 9), fg="#9aa0a6",
                 bg="#1a1d27").pack(pady=(10, 0))
        self.pin_var = tk.StringVar(value="------")
        tk.Label(self.pin_frame, textvariable=self.pin_var, font=("Consolas", 28, "bold"),
                 fg="#4fd1c5", bg="#1a1d27").pack(pady=(0, 10))

        tk.Label(self.pin_frame, text="Open this link on the OTHER laptop:",
                 font=("Segoe UI", 10, "bold"), fg="#e6e6e6", bg="#1a1d27").pack(pady=(4, 2))
        link_row = tk.Frame(self.pin_frame, bg="#1a1d27")
        link_row.pack(pady=(2, 14))
        self.link_entry = tk.Entry(link_row, font=("Segoe UI", 10, "bold"), width=32,
                                    justify="center", fg="#4fd1c5", readonlybackground="#0f1117",
                                    relief="flat")
        self.link_entry.insert(0, VIEWER_LINK)
        self.link_entry.config(state="readonly")
        self.link_entry.pack(side="left", padx=(0, 6), ipady=4)
        tk.Button(link_row, text="📋 Copy", font=("Segoe UI", 9, "bold"), command=self.copy_link,
                  bg="#2d3142", fg="white", relief="flat", padx=8).pack(side="left")

        self.pin_frame.pack(fill="x", padx=30, pady=10)

    def on_start(self):
        self.start_btn.config(state="disabled")
        self.status_var.set("Connecting to signaling server...")
        start_agent_thread(self.on_pin_ready, self.on_status, self.on_error, self.on_stopped)
        self.stop_btn.config(state="normal")

    def on_pin_ready(self, code):
        self.after(0, lambda: self.pin_var.set(code))

    def on_status(self, text):
        self.after(0, lambda: self.status_var.set(text))

    def on_error(self, msg):
        self.after(0, lambda: self._show_error(msg))

    def _show_error(self, msg):
        self.status_var.set("Error")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        messagebox.showerror("Connection error", f"Could not connect:\n{msg}")

    def on_stop(self):
        stop_agent()
        self.status_var.set("Stopped")
        self.pin_var.set("------")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def on_stopped(self):
        pass

    def copy_link(self):
        self.clipboard_clear()
        self.clipboard_append(VIEWER_LINK)


if __name__ == "__main__":
    app = App()
    app.mainloop()