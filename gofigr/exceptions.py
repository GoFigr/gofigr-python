"""\
Copyright (c) 2022-2025, Flagstaff Solutions, LLC
All rights reserved.

"""

class UnauthorizedError(RuntimeError):
    """\
    Thrown if user doesn't have permissions to perform an action.
    """
    pass


class MethodNotAllowedError(RuntimeError):
    """\
    Thrown if a given REST action is not supported/allowed.
    """
    pass
