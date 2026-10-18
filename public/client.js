const joinBox = document.getElementById('joinBox');
const viewerWrap = document.getElementById('viewerWrap');
const pinInput = document.getElementById('pinInput');
const joinBtn = document.getElementById('joinBtn');
const statusEl = document.getElementById('status');
const connStateEl = document.getElementById('connState');
const video = document.getElementById('screen');

let ws = null;
let pc = null;
let dataChannel = null;

// Ask OUR OWN server for TURN credentials — it holds the Cloudflare
// secret server-side and hands back short-lived, safe-to-use credentials.
async function getIceServers() {
  try {
    const res = await fetch('/turn-credentials');
    const data = await res.json();
    return data.iceServers;
  } catch (e) {
    console.warn('Could not fetch TURN credentials, using STUN only.', e);
    return [{ urls: 'stun:stun.l.google.com:19302' }];
  }
}

function connect() {
  const code = pinInput.value.trim();
  if (!/^\d{6}$/.test(code)) {
    statusEl.textContent = 'Enter a valid 6-digit PIN';
    return;
  }

  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${protocol}://${location.host}`);

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: 'viewer:join', code }));
  };

  ws.onmessage = async (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === 'joined') {
      joinBox.style.display = 'none';
      viewerWrap.style.display = 'flex';
      statusEl.textContent = '';
      connStateEl.textContent = 'Waiting for connection from host...';
    } else if (msg.type === 'error') {
      statusEl.textContent = msg.message;
    } else if (msg.type === 'host-left') {
      statusEl.textContent = 'Host disconnected.';
      viewerWrap.style.display = 'none';
      joinBox.style.display = 'flex';
    } else if (msg.type === 'signal:offer') {
      await handleOffer(msg.offer);
    }
  };

  ws.onerror = () => { statusEl.textContent = 'Connection error.'; };
}

async function handleOffer(offer) {
  const iceServers = await getIceServers();
  pc = new RTCPeerConnection({ iceServers });

  pc.ontrack = (e) => {
    video.srcObject = e.streams[0];
    connStateEl.textContent = '✅ Connected — live peer-to-peer';
    video.play().catch((err) => {
      console.warn('Autoplay blocked, click the video to start:', err);
      connStateEl.textContent = '✅ Connected — click the video to start it';
      video.addEventListener('click', () => video.play(), { once: true });
    });
  };

  pc.ondatachannel = (e) => {
    dataChannel = e.channel;
  };

  pc.oniceconnectionstatechange = () => {
    console.log('ICE connection state:', pc.iceConnectionState);
    if (pc.iceConnectionState === 'failed') {
      connStateEl.textContent = '⚠️ Connection failed';
    } else if (pc.iceConnectionState === 'disconnected') {
      connStateEl.textContent = '⚠️ Connection unstable, trying to recover...';
    } else if (pc.iceConnectionState === 'connected' || pc.iceConnectionState === 'completed') {
      connStateEl.textContent = '✅ Connected — live peer-to-peer';
    }
  };

  await pc.setRemoteDescription(new RTCSessionDescription(offer));

  // Force VP8 codec — avoids black-screen issues some H264 setups cause
  try {
    const transceiver = pc.getTransceivers().find(t => t.receiver && t.receiver.track && t.receiver.track.kind === 'video');
    if (transceiver && transceiver.setCodecPreferences && RTCRtpReceiver.getCapabilities) {
      const caps = RTCRtpReceiver.getCapabilities('video');
      const vp8 = caps.codecs.filter(c => c.mimeType === 'video/VP8');
      if (vp8.length) transceiver.setCodecPreferences(vp8);
    }
  } catch (e) {
    console.warn('Could not set codec preference:', e);
  }

  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);

  // Wait until all ICE candidates are gathered so the SDP we send is complete
  await waitForIceGatheringComplete(pc);

  ws.send(JSON.stringify({ type: 'signal:answer', answer: pc.localDescription }));
}

function waitForIceGatheringComplete(peerConn) {
  return new Promise((resolve) => {
    if (peerConn.iceGatheringState === 'complete') {
      resolve();
      return;
    }
    function check() {
      if (peerConn.iceGatheringState === 'complete') {
        peerConn.removeEventListener('icegatheringstatechange', check);
        resolve();
      }
    }
    peerConn.addEventListener('icegatheringstatechange', check);
  });
}

joinBtn.addEventListener('click', connect);
pinInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') connect(); });

function sendControl(payload) {
  if (dataChannel && dataChannel.readyState === 'open') {
    dataChannel.send(JSON.stringify(payload));
  }
}

// ---- Mouse control (sent directly P2P via the data channel) ----
let lastMoveSent = 0;
video.addEventListener('mousemove', (e) => {
  const now = Date.now();
  if (now - lastMoveSent < 50) return;
  lastMoveSent = now;
  const rect = video.getBoundingClientRect();
  const x = (e.clientX - rect.left) / rect.width;
  const y = (e.clientY - rect.top) / rect.height;
  sendControl({ action: 'move', x, y });
});

video.addEventListener('mousedown', (e) => {
  const rect = video.getBoundingClientRect();
  const x = (e.clientX - rect.left) / rect.width;
  const y = (e.clientY - rect.top) / rect.height;
  const button = e.button === 2 ? 'right' : 'left';
  sendControl({ action: 'click', x, y, button });
  video.focus();
});

video.addEventListener('contextmenu', (e) => e.preventDefault());

video.addEventListener('wheel', (e) => {
  e.preventDefault();
  // One normal mouse-wheel notch is usually ~100 deltaY — scale that up
  // to a clearly noticeable scroll amount instead of a tiny nudge.
  const notches = e.deltaY / 100;
  let amount = Math.round(-notches * 6);
  amount = Math.max(-20, Math.min(20, amount));
  sendControl({ action: 'scroll', amount });
}, { passive: false });

video.addEventListener('keydown', (e) => {
  e.preventDefault();
  sendControl({ action: 'key_down', key: e.key });
});

video.addEventListener('keyup', (e) => {
  e.preventDefault();
  sendControl({ action: 'key_up', key: e.key });
});