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

import asyncio
import json
import cv2
import numpy as np
import mss
import pyautogui
import websockets
import aiohttp
import av
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer, VideoStreamTrack

pyautogui.FAILSAFE = False

async def get_ice_servers(server_url):
    """Ask OUR OWN signaling server for TURN credentials — it holds the
    Cloudflare secret server-side and hands back short-lived credentials.
    Falls back to STUN-only if that call fails for any reason."""
    http_url = server_url.replace('wss://', 'https://').replace('ws://', 'http://')
    http_url = http_url.rstrip('/') + '/turn-credentials'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(http_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
        servers = []
        for entry in data.get('iceServers', []):
            servers.append(RTCIceServer(
                urls=entry['urls'],
                username=entry.get('username'),
                credential=entry.get('credential'),
            ))
        print(f"[info] Loaded {len(servers)} ICE servers.")
        return servers
    except Exception as e:
        print(f"[warning] Could not fetch TURN credentials ({e}), using STUN only.")
        return [RTCIceServer(urls="stun:stun.l.google.com:19302")]


class ScreenTrack(VideoStreamTrack):
    """Captures the screen and offers it as a live WebRTC video track."""

    def __init__(self, fps=20):
        super().__init__()
        self._sct = mss.mss()
        self._monitor = self._sct.monitors[1]
        self._frame_count = 0

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        raw = np.array(self._sct.grab(self._monitor))
        img = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

        self._frame_count += 1
        if self._frame_count % 30 == 1:  # print every ~30 frames
            print(f"[ScreenTrack] frame #{self._frame_count}, shape={img.shape}, "
                  f"mean_brightness={img.mean():.1f} (0=pure black, 255=pure white)")

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


async def _heartbeat(ws, stop_event):
    """Send a small ping every 20s so Render's proxy never sees this
    connection as idle and closes it underneath us."""
    try:
        while not stop_event.is_set():
            await asyncio.sleep(20)
            await ws.send(json.dumps({'type': 'ping'}))
    except Exception:
        pass  # signaling loop will notice the disconnect and handle it


async def run_agent(server_url, on_pin_ready, on_status, stop_event):
    """
    Connects to the signaling server, waits for a viewer, and sets up a
    direct WebRTC connection. Calls on_pin_ready(code) once the PIN is
    issued, and on_status(text) for status updates.

    IMPORTANT: if the signaling connection drops after a peer connection
    is already established, we do NOT treat that as fatal — the actual
    video/control keeps flowing peer-to-peer regardless of the signaling
    link, so we just stop here quietly instead of tearing anything down.
    """
    screen_w, screen_h = pyautogui.size()
    pcs = {}  # viewerId -> RTCPeerConnection
    had_connection = False
    ice_servers = await get_ice_servers(server_url)

    try:
        async with websockets.connect(server_url, max_size=None, open_timeout=60,
                                       ping_interval=20, ping_timeout=20) as ws:
            await ws.send(json.dumps({'type': 'host:register'}))
            reply = json.loads(await ws.recv())
            code = reply['code']
            on_pin_ready(code)
            on_status("Waiting for a viewer to connect...")

            hb_task = asyncio.ensure_future(_heartbeat(ws, stop_event))

            try:
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

                        pc.addTrack(ScreenTrack())
                        channel = pc.createDataChannel('control')

                        @channel.on('message')
                        def on_message(message):
                            handle_control_message(message, screen_w, screen_h)

                        offer = await pc.createOffer()
                        await pc.setLocalDescription(offer)  # waits for full ICE gathering

                        await ws.send(json.dumps({
                            'type': 'signal:offer',
                            'to': viewer_id,
                            'offer': {'sdp': pc.localDescription.sdp, 'type': pc.localDescription.type},
                        }))
                        on_status("✅ Live — connected to viewer (peer-to-peer)")
                        had_connection = True

                    elif mtype == 'signal:answer':
                        viewer_id = msg['from']
                        pc = pcs.get(viewer_id)
                        if pc:
                            answer = RTCSessionDescription(sdp=msg['answer']['sdp'], type=msg['answer']['type'])
                            await pc.setRemoteDescription(answer)
            finally:
                hb_task.cancel()

    except Exception as e:
        if had_connection:
            # Screen share is already live P2P — signaling loss doesn't kill it.
            on_status("⚠️ Signaling link dropped, but screen share is still live.")
        else:
            raise  # never managed to connect at all — this IS a real failure

    # Keep this coroutine alive (and therefore the event loop + existing
    # peer connections) until the user explicitly clicks Stop.
    await stop_event.wait()

    for pc in pcs.values():
        await pc.close()