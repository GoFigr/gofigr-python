"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

The metadata proxy uses the GoFigr server to securely pass information from JavaScript to the GoFigr plugin
running inside the Python kernel. This mechanism enables the frontend to securely communicate regardless
of how Jupyter is running, i.e. it works even with password/token auth and SSH tunneling.

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
from urllib.parse import urljoin

import pkg_resources
from IPython.core.display import Javascript
from websockets.server import serve

_CALLBACK_THREAD = None
_STOP_CALLBACK_THREAD = False


QUEUE_MSG_STARTED = "started"
QUEUE_MSG_DONE = "done"


def callback_thread(callback, queue, proxy):
    """Periodically polls the queue for messages, and calls the callback function (if specified)"""
    queue.put(QUEUE_MSG_STARTED)

    while not _STOP_CALLBACK_THREAD:
        proxy.fetch()
        if proxy.updated is not None:  # we have metadata
            callback(proxy)
            queue.put(QUEUE_MSG_DONE)
            return

        time.sleep(0.25)


def wait_for_metadata(queue, timeout):
    def _waiter():
        try:
            res = queue.get(block=True, timeout=timeout)
            if res != QUEUE_MSG_DONE:
                print(f"Unexpected proxy message: {res}", file=sys.stderr)

            queue.task_done()
        except Exception as e:
            print(f"Unable to retrieve metadata from the GoFigr proxy: {e}", file=sys.stderr)

    return _waiter


def run_proxy_async(gf, callback):
    """\
    Starts the GoFigr WebSocket listener in the background. Blocks until the listener is setup and ready
    to process messages.

    :param gf: GoFigr client instance
    :param callback: function to call with received messages
    :return: port that the listener was started on

    """
    global _CALLBACK_THREAD, _STOP_CALLBACK_THREAD

    if _CALLBACK_THREAD is not None:
        _STOP_CALLBACK_THREAD = True
        _CALLBACK_THREAD.join(2.0)

    mp_queue = multiprocessing.JoinableQueue()

    proxy = gf.MetadataProxy().create()

    try:
        _STOP_CALLBACK_THREAD = False
        _CALLBACK_THREAD = Thread(target=callback_thread,
                                  args=(callback, mp_queue, proxy))
        _CALLBACK_THREAD.start()

        res = mp_queue.get(block=True, timeout=5)
        if res != QUEUE_MSG_STARTED:
            raise queue.Empty()

        mp_queue.task_done()

    except queue.Empty:
        print("GoFigr JavaScript proxy did not start and functionality may be limited.",
              file=sys.stderr)

    return proxy, wait_for_metadata(mp_queue, timeout=5)


def get_javascript_loader(gf, proxy):
    endpoint = urljoin(gf.api_url, "metadata/" + proxy.token)
    loader_body = pkg_resources.resource_string("gofigr.resources", "loader.js").decode('utf-8')
    loader = f"const endpoint=\"{endpoint}\";\n" + loader_body
    return Javascript(loader)
