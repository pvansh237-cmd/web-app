/**
 * server.js — WebRTC SIGNALING server only.
 *
 * IMPORTANT: No video/screen data passes through this server at all.
 * It only relays tiny text messages (SDP offer/answer) to set up a
 * DIRECT peer-to-peer connection between the host and the viewer.
 * Once connected, video + control flow straight between the two laptops.
 *
 * This is why it stays fast even on Render's free tier — the server's
 * job is just a few KB of text, not continuous video.
 */

const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const path = require('path');

const app = express();
app.use(express.static(path.join(__dirname, 'public')));

// Both the browser and the Python agent ask THIS server for TURN
// credentials — the ExpressTURN username/password stay only in Render's
// environment variables, never in any file that gets committed.
app.get('/turn-credentials', (req, res) => {
  // Try env-configured TURN first (set these in Render if you sign up
  // for ExpressTURN or another provider later)
  const username = process.env.TURN_USERNAME;
  const password = process.env.TURN_PASSWORD;
  const host = process.env.TURN_HOST;

  if (username && password && host) {
    return res.json({
      iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: `turn:${host}`, username, credential: password },
        { urls: `turn:${host}?transport=tcp`, username, credential: password },
      ],
    });
  }

  // No account needed for this one — zero setup, try it directly.
  res.json({
    iceServers: [
      { urls: 'stun:stun.l.google.com:19302' },
      { urls: 'turn:freestun.net:3478', username: 'free', credential: 'free' },
    ],
  });
});

const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

// code -> { hostWs, viewers: Map<id, ws> }
const rooms = new Map();

function generateCode() {
  let code;
  do {
    code = Math.floor(100000 + Math.random() * 900000).toString();
  } while (rooms.has(code));
  return code;
}

wss.on('connection', (ws) => {
  ws.id = Math.random().toString(36).slice(2, 10);
  ws.role = null;
  ws.code = null;

  ws.on('message', (data) => {
    let msg;
    try {
      msg = JSON.parse(data.toString());
    } catch {
      return;
    }

    if (msg.type === 'host:register') {
      const code = generateCode();
      ws.role = 'host';
      ws.code = code;
      rooms.set(code, { hostWs: ws, viewers: new Map() });
      ws.send(JSON.stringify({ type: 'code', code }));
      console.log(`[host] room ${code} created`);
      return;
    }

    if (msg.type === 'viewer:join') {
      const room = rooms.get(msg.code);
      if (!room) {
        ws.send(JSON.stringify({ type: 'error', message: 'Invalid code or host offline' }));
        return;
      }
      ws.role = 'viewer';
      ws.code = msg.code;
      room.viewers.set(ws.id, ws);
      ws.send(JSON.stringify({ type: 'joined' }));
      room.hostWs.send(JSON.stringify({ type: 'host:viewer-joined', viewerId: ws.id }));
      console.log(`[viewer] ${ws.id} joined room ${msg.code}`);
      return;
    }

    // Relay the offer (host -> specific viewer)
    if (msg.type === 'signal:offer') {
      const room = rooms.get(ws.code);
      if (room) {
        const viewerWs = room.viewers.get(msg.to);
        if (viewerWs) {
          viewerWs.send(JSON.stringify({ type: 'signal:offer', from: ws.id, offer: msg.offer }));
        }
      }
      return;
    }

    // Relay the answer (viewer -> host)
    if (msg.type === 'signal:answer') {
      const room = rooms.get(ws.code);
      if (room && room.hostWs) {
        room.hostWs.send(JSON.stringify({ type: 'signal:answer', from: ws.id, answer: msg.answer }));
      }
      return;
    }
  });

  ws.on('close', () => {
    if (ws.role === 'host' && ws.code) {
      const room = rooms.get(ws.code);
      if (room) {
        for (const v of room.viewers.values()) {
          v.send(JSON.stringify({ type: 'host-left' }));
        }
      }
      rooms.delete(ws.code);
      console.log(`[host] room ${ws.code} closed`);
    } else if (ws.role === 'viewer' && ws.code) {
      const room = rooms.get(ws.code);
      if (room) room.viewers.delete(ws.id);
    }
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => console.log(`✅ Signaling server running: http://localhost:${PORT}`));