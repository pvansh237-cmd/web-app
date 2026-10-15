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

let ICE_SERVERS = [{ urls: 'stun:stun.l.google.com:19302' }];

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
      if (msg.iceServers) ICE_SERVERS = msg.iceServers;
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
  pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });

  pc.ontrack = (e) => {
    video.srcObject = e.streams[0];
    video.play().catch(() => {});
  };

  pc.ondatachannel = (e) => {
    dataChannel = e.channel;
  };

  pc.onconnectionstatechange = () => {
    const st = pc.connectionState;
    console.log('connectionState:', st, 'ice:', pc.iceConnectionState);
    if (st === 'connected') connStateEl.textContent = '✅ Connected — live peer-to-peer';
    else if (st === 'failed') connStateEl.textContent = '❌ Connection failed (network blocked P2P — TURN needed)';
    else if (st === 'disconnected') connStateEl.textContent = '⚠️ Connection lost';
    else connStateEl.textContent = 'Connecting... (' + st + ')';
  };

  await pc.setRemoteDescription(new RTCSessionDescription(offer));
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
  sendControl({ action: 'scroll', amount: e.deltaY > 0 ? -2 : 2 });
}, { passive: false });

video.addEventListener('keydown', (e) => {
  e.preventDefault();
  sendControl({ action: 'key_down', key: e.key });
});

video.addEventListener('keyup', (e) => {
  e.preventDefault();
  sendControl({ action: 'key_up', key: e.key });
});
