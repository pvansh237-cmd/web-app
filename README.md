# Remote Screen Control — WebRTC (Real Peer-to-Peer Fix)

## Ye pehle wale se kaise alag hai

**Pehle (purana tareeka):** Target laptop → Render server → Viewer laptop.
Video Render ke weak free CPU se hoke guzarta tha, isliye kabhi slow, kabhi
blur hota tha — Render hi bottleneck tha.

**Ab (WebRTC):** Target laptop → **seedha** → Viewer laptop (direct P2P
connection, jaisa Google Meet/Zoom karte hain). Render sirf connection jodwane
ke liye ek baar chhota sa text message (SDP) relay karta hai — iske baad
Render ka koi role nahi, video uske through jaata hi nahi.

**Natija:** Speed aur clarity ab sirf tumhare dono laptops ke apne internet pe
depend karti hai, Render ki weak CPU beech me nahi aati. Isliye ye real,
permanent fix hai.

## Setup

### 1. Server deploy karo (same Render process, bas naya code)
```bash
npm install
npm start      # local test ke liye
```
Phir GitHub pe push karke Render pe deploy karo (jaisa pehle kiya tha).

### 2. Target laptop pe agent install karo
```bash
cd agent
pip install -r requirements.txt
```

> ⚠️ `aiortc` install hone me thoda time lag sakta hai (2-5 min) kyunki ye
> video encoding libraries bhi saath me install karta hai. Agar Windows pe
> error aaye "Microsoft Visual C++ 14.0 required", toto "Microsoft C++ Build
> Tools" install karna padega (ek baar ka setup): https://visualstudio.microsoft.com/visual-cpp-build-tools/

### 3a. Terminal se chalana ho toh:
```bash
python agent.py --server wss://web-app-swqz.onrender.com
```

### 3b. GUI app (.exe) banana ho toh:
```bash
pyinstaller --onefile --windowed --name ScreenShareAgent gui_agent.py
```
`dist/ScreenShareAgent.exe` ban jayegi — double-click karo, "Start Sharing"
dabao, PIN dikhega.

### 4. Viewer laptop pe
Bas browser me Render URL kholo, PIN daalo, Connect dabao. Video ab
**seedha** target laptop se aayega — koi relay nahi.

## Important notes

- **STUN server use ho raha hai** (`stun.l.google.com`) connection jodne ke
  liye — ye Google ka free public server hai, isse dono laptops ek doosre
  ko network ke through dhoondh paate hain chahe alag WiFi pe hon.
- Agar dono laptop **bahut restrictive network** (jaise college ka strict
  firewall) pe hon, kabhi-kabhi direct P2P block ho sakta hai — aise case me
  TURN server chahiye hota hai (zyada advanced setup), par zyadatar home/
  college WiFi pe ye seedha kaam karega.
- Control (mouse/keyboard) bhi ab seedha P2P jaata hai DataChannel ke through
  — Render us par bhi nahi chhuta.

## File structure
```
webrtc-remote-control/
├── server.js              # signaling only — ab bahut halka hai
├── package.json
├── public/
│   ├── index.html          # video element wali website
│   └── client.js           # browser-side WebRTC logic
└── agent/
    ├── agent_core.py        # shared WebRTC logic
    ├── agent.py              # terminal version
    ├── gui_agent.py           # GUI/.exe version
    └── requirements.txt
```
