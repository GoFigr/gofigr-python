"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

GoFigr listener is a small embedded WebSocket server made available
to Javascript calls within Jupyter/JupyterLab notebooks. We
use it to capture notebook metadata not readily available to IPython,
such as the server URL or notebook name.

"""

# pylint: disable=global-statement

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
_CALLBACK_THREAD = None
_STOP_CALLBACK_THREAD = False
_CALLBACK = None
_PORT = None


async def handle_message(websocket):
    """Handles WebSocket messages"""
    async for message in websocket:
        try:
            data = json.loads(message)
            if data['message_type'] == "metadata":
                _QUEUE.put(data)

            await websocket.send("ok")
        except Exception:  # pylint: disable=broad-exception-caught
            traceback.print_exc()
            await websocket.send("error")


def run_listener(port, callback, queue_instance):
    """Main entry point to the listener process"""
    global _CALLBACK, _QUEUE
    _CALLBACK = callback
    _QUEUE = queue_instance

    async def _async_helper():
        queue_instance.put("started")  # will unblock the calling method in the main Jupyter thread
        async with serve(handle_message, "0.0.0.0", port):
            await asyncio.Future()  # run forever

    asyncio.run(_async_helper())


def callback_thread():
    """Periodically polls the WebSocket queue for messages, and calls the callback function (if specified)"""
    if _CALLBACK is None:
        return

    # We need to persist initial values in case the user re-runs the notebook without restarting the kernel.
    # In that case, _QUEUE and _CALLBACK may get updated with the intention to start a new listener, and this
    # thread may inadvertently end up consuming messages from the new queue. This ensures we only ever
    # consume messages from the initial queue.
    thread_queue = _QUEUE
    callback_func = _CALLBACK

    while not _STOP_CALLBACK_THREAD and thread_queue is not None:
        try:
            res = thread_queue.get(block=True, timeout=0.25)
            if res is not None:
                callback_func(res)
        except queue.Empty:
            continue


def run_listener_async(callback):
    """\
    Starts the GoFigr WebSocket listener in the background. Blocks until the listener is setup and ready
    to process messages.

    :param callback: function to call with received messages
    :return: port that the listener was started on

    """
    global _SERVER_PROCESS, _CALLBACK, _PORT, _QUEUE, _CALLBACK_THREAD, _STOP_CALLBACK_THREAD
    if _SERVER_PROCESS is not None:
        _SERVER_PROCESS.terminate()

    if _CALLBACK_THREAD is not None:
        _STOP_CALLBACK_THREAD = True
        _CALLBACK_THREAD.join(2.0)

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
        time.sleep(1)
        res = _QUEUE.get(block=True, timeout=5)
        if res != "started":
            raise queue.Empty()

        _STOP_CALLBACK_THREAD = False
        _CALLBACK_THREAD = Thread(target=callback_thread)
        _CALLBACK_THREAD.start()
    except queue.Empty:
        print("WebSocket did not start and GoFigr functionality may be limited.",
              file=sys.stderr)

    return _PORT
