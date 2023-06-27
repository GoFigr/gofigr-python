"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

GoFigr listener is a small embedded HTTP server made available
to Javascript calls within Jupyter/JupyterLab notebooks. We
use it to capture notebook metadata not readily available to IPython,
such as the server URL or notebook name.

"""
import json
import multiprocessing
import queue
import socket
import sys
import time
import traceback
from multiprocessing import Process

import asyncio
from threading import Thread

from websockets.server import serve

_QUEUE = None
_SERVER_PROCESS = None
_CALLBACK = None
_PORT = None


async def echo(websocket):
    async for message in websocket:
        try:
            data = json.loads(message)
            if data['message_type'] == "metadata":
                _QUEUE.put(data)

            await websocket.send("ok")
        except:
            traceback.print_exc()
            await websocket.send("error")


def run_listener(port, callback, queue):
    global _CALLBACK, _QUEUE
    _CALLBACK = callback
    _QUEUE = queue

    async def _async_helper():
        print(f"Listening on port {port}")

        queue.put("started")
        async with serve(echo, "localhost", port):
            await asyncio.Future()  # run forever

    asyncio.run(_async_helper())


def callback_thread():
    if _CALLBACK is None:
        return

    while True:
        if _QUEUE is not None:
            try:
                res = _QUEUE.get(block=True, timeout=0.5)
                if res is not None:
                    _CALLBACK(res)
            except queue.Empty:
                continue
        else:
            time.sleep(0.5)


def run_listener_async(callback):
    global _SERVER_PROCESS, _CALLBACK, _PORT, _QUEUE
    _QUEUE = multiprocessing.Queue()

    # First find an available port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('localhost', 0))
    _PORT = sock.getsockname()[1]
    sock.close()

    _CALLBACK = callback
    _SERVER_PROCESS = Process(target=run_listener, args=(_PORT, _CALLBACK, _QUEUE))
    _SERVER_PROCESS.start()

    try:
        res = _QUEUE.get(block=True, timeout=5)
        if res != "started":
            raise queue.Empty()

        ct = Thread(target=callback_thread)
        ct.start()
    except queue.Empty:
        print("WebSocket did not start and GoFigr functionality may be limited.",
              file=sys.stderr)

    return _PORT
