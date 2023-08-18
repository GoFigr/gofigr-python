"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
from datetime import datetime

ENABLED = False
LEVEL = 0


class MeasureExecution:
    """Context manager which measures execution time"""
    def __init__(self, name):
        """
        :param name: name of the context being measured
        """
        self.name = name
        self.start_time = None
        self.duration = None

    def __enter__(self):
        global LEVEL  # pylint: disable=global-statement
        self.start_time = datetime.now()
        LEVEL += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        global LEVEL  # pylint: disable=global-statement
        self.duration = datetime.now() - self.start_time
        if ENABLED:
            print(("  " * (LEVEL - 1)) + f"{self.name}: took {self.duration.total_seconds():.2f}s")

        LEVEL -= 1
        return False  # propagate exceptions (if any)
