"""\
Copyright (c) 2022-2025, Flagstaff Solutions, LLC
All rights reserved.

"""

DISPLAY_TRAP = None


def set_trap(func):
    """\
    Sets a display trap

    :param func: function to call whenever data is being displayed
    :return: trap function

    """
    global DISPLAY_TRAP
    DISPLAY_TRAP = func
    return func


class GfDisplayPublisher:
    """\
    Custom IPython DisplayPublisher which traps all calls to publish() (e.g. when display(...) is called).

    """
    def __init__(self, pub):
        """

        :param pub: Publisher to wrap around. We delegate all calls to this publisher unless trapped.
        """
        self.pub = pub

    def publish(self, data, *args, **kwargs):
        """
        IPython calls this method whenever it needs data displayed. Our function traps the call
        and calls DISPLAY_TRAP instead, giving it an option to suppress the figure from being displayed.

        We use this trap to publish the figure if auto_publish is True. Suppression is useful
        when we want to show a watermarked version of the figure, and prevents it from being showed twice (once
        with the watermark inside the trap, and once without in the originating call).

        :param data: dictionary of mimetypes -> data
        :param args: implementation-dependent
        :param kwargs: implementation-dependent
        :return: None

        """

        # Python doesn't support assignment to variables in closure scope, so we use a mutable list instead
        is_display_suppressed = [False]
        def suppress_display():
            is_display_suppressed[0] = True

        if DISPLAY_TRAP is not None:
            trap = DISPLAY_TRAP
            with SuppressDisplayTrap():
                trap(data, suppress_display=suppress_display)

        if not is_display_suppressed[0]:
            self.pub.publish(data, *args, **kwargs)

    def __getattr__(self, item):
        """\
        Delegates to self.pub

        :param item:
        :return:
        """
        if item == "pub":
            return super().__getattribute__(item)

        return getattr(self.pub, item)

    def __setattr__(self, key, value):
        """\
        Delegates to self.pub

        :param key:
        :param value:
        :return:
        """
        if key == "pub":
            super().__setattr__(key, value)

        return setattr(self.pub, key, value)

    def clear_output(self, *args, **kwargs):
        """IPython's clear_output. Defers to self.pub"""
        return self.pub.clear_output(*args, **kwargs)


class SuppressDisplayTrap:
    """\
    Context manager which temporarily suspends all display traps.
    """
    def __init__(self):
        self.trap = None

    def __enter__(self):
        global DISPLAY_TRAP
        self.trap = DISPLAY_TRAP
        DISPLAY_TRAP = None

    def __exit__(self, exc_type, exc_val, exc_tb):
        global DISPLAY_TRAP
        DISPLAY_TRAP = self.trap
        self.trap = None
