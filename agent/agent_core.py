"""
agent_core.py
Shared WebRTC logic used by both the console agent (agent.py) and the
desktop GUI app (gui_agent.py).

Architecture:
- Connects to the signaling server (server.js) only to exchange a tiny
  SDP offer/answer — a few KB of text, once per connection.
- Once connected, screen video flows DIRECTLY to the viewer's browser
  over a real WebRTC peer-to-peer connection (same tech as Google Meet).
- Mouse/keyboard commands from the viewer arrive over a WebRTC
  DataChannel — also direct, not through the signaling server.

This is why performance stays smooth regardless of how weak the
signaling server's free hosting tier is: it's barely used.
"""

import json
import logging
import cv2
import numpy as np
import mss
import pyautogui
import websockets
import av
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer, VideoStreamTrack

pyautogui.FAILSAFE = False

logging.basicConfig(level=logging.WARNING)


def build_ice_servers(raw):
    servers = []
    for s in raw or [{'urls': 'stun:stun.l.google.com:19302'}]:
        servers.append(RTCIceServer(urls=s['urls'], username=s.get('username'),
                                    credential=s.get('credential')))
    return servers


class ScreenTrack(VideoStreamTrack):
    """Captures the screen and offers it as a live WebRTC video track."""

    def __init__(self, fps=20):
        super().__init__()
        self._sct = mss.mss()
        self._monitor = self._sct.monitors[1]

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        raw = np.array(self._sct.grab(self._monitor))
        img = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        h, w = img.shape[:2]
        if w > 1280:  # downscale so encoding stays smooth
            img = cv2.resize(img, (1280, (int(1280 * h / w) // 2) * 2))
        elif w % 2 or h % 2:
            img = img[: h - h % 2, : w - w % 2]
        frame = av.VideoFrame.from_ndarray(img, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


def map_key(browser_key: str):
    special = {
        ' ': 'space', 'Enter': 'enter', 'Backspace': 'backspace', 'Tab': 'tab',
        'Escape': 'esc', 'ArrowUp': 'up', 'ArrowDown': 'down',
        'ArrowLeft': 'left', 'ArrowRight': 'right', 'Shift': 'shift',
        'Control': 'ctrl', 'Alt': 'alt', 'Meta': 'win', 'Delete': 'delete',
        'CapsLock': 'capslock',
    }
    if browser_key in special:
        return special[browser_key]
    if len(browser_key) == 1:
        return browser_key.lower()
    return None


def handle_control_message(raw_msg, screen_w, screen_h):
    try:
        msg = json.loads(raw_msg)
    except json.JSONDecodeError:
        return
    action = msg.get('action')
    try:
        if action == 'move':
            pyautogui.moveTo(int(msg['x'] * screen_w), int(msg['y'] * screen_h))
        elif action == 'click':
            pyautogui.click(int(msg['x'] * screen_w), int(msg['y'] * screen_h),
                             button=msg.get('button', 'left'))
        elif action == 'scroll':
            pyautogui.scroll(int(msg.get('amount', 0)))
        elif action == 'key_down':
            key = map_key(msg['key'])
            if key:
                pyautogui.keyDown(key)
        elif action == 'key_up':
            key = map_key(msg['key'])
            if key:
                pyautogui.keyUp(key)
    except Exception as e:
        print('control exec error:', e)


async def run_agent(server_url, on_pin_ready, on_status, stop_event):
    """
    Connects to the signaling server, waits for a viewer, and sets up a
    direct WebRTC connection. Calls on_pin_ready(code) once the PIN is
    issued, and on_status(text) for status updates.
    """
    screen_w, screen_h = pyautogui.size()
    pcs = {}  # viewerId -> RTCPeerConnection

    async with websockets.connect(server_url, max_size=None, open_timeout=60) as ws:
        await ws.send(json.dumps({'type': 'host:register'}))
        reply = json.loads(await ws.recv())
        code = reply['code']
        ice_servers = build_ice_servers(reply.get('iceServers'))
        on_pin_ready(code)
        on_status("Waiting for a viewer to connect...")

        async for raw in ws:
            if stop_event.is_set():
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mtype = msg.get('type')

            if mtype == 'host:viewer-joined':
                viewer_id = msg['viewerId']
                config = RTCConfiguration(iceServers=ice_servers)
                pc = RTCPeerConnection(configuration=config)
                pcs[viewer_id] = pc

                @pc.on('connectionstatechange')
                async def on_state(pc=pc):
                    st = pc.connectionState
                    if st == 'connected':
                        on_status("✅ Live — connected to viewer (peer-to-peer)")
                    elif st == 'failed':
                        on_status("❌ P2P connection failed (network blocked — TURN needed)")
                    else:
                        on_status(f"WebRTC state: {st}")

                pc.addTrack(ScreenTrack())
                channel = pc.createDataChannel('control')

                @channel.on('message')
                def on_message(message):
                    handle_control_message(message, screen_w, screen_h)

                offer = await pc.createOffer()
                await pc.setLocalDescription(offer)  # aiortc waits for full ICE gathering here

                await ws.send(json.dumps({
                    'type': 'signal:offer',
                    'to': viewer_id,
                    'offer': {'sdp': pc.localDescription.sdp, 'type': pc.localDescription.type},
                }))
                on_status("Offer sent, connecting...")

            elif mtype == 'signal:answer':
                viewer_id = msg['from']
                pc = pcs.get(viewer_id)
                if pc:
                    answer = RTCSessionDescription(sdp=msg['answer']['sdp'], type=msg['answer']['type'])
                    await pc.setRemoteDescription(answer)

    for pc in pcs.values():
        await pc.close()
