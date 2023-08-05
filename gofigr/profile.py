"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
from datetime import datetime

ENABLED = False


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
        self.start_time = datetime.now()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.duration = datetime.now() - self.start_time
        if ENABLED:
            print(f"{self.name}: took {self.duration.total_seconds():.2f}s")
        return False  # propagate exceptions (if any)
