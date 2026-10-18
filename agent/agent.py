"""
agent.py — console version. Run this on the target laptop.

Run:
    pip install -r requirements.txt
    python agent.py --server wss://web-app-swqz.onrender.com
"""

import argparse
import asyncio
from agent_core import run_agent


def on_pin_ready(code):
    print('=' * 50)
    print(' LIVE SCREEN SHARE + CONTROL — HOST AGENT (WebRTC)')
    print('=' * 50)
    print(f' PIN: {code}')
    print(' Share this PIN with the viewer. No install needed there.')
    print('=' * 50)


def on_status(text):
    print(f'[status] {text}')


async def main(server_url):
    stop_event = asyncio.Event()
    await run_agent(server_url, on_pin_ready, on_status, stop_event)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', default='wss://web-app-swqz.onrender.com')
    args = parser.parse_args()
    asyncio.run(main(args.server))