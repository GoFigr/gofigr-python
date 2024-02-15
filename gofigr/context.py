"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""


# pylint: disable=protected-access
class RevisionContext:
    """\
    Stores publishing context for a revision. We created this class so that we don't have to pass
    a lot of disjointed state around.

    """
    def __init__(self, backend=None, extension=None):
        """\

        :param backend: GoFigr backend which originated this figure
        :param extension: GoFigr Jupyter extension
        """
        self.backend = backend
        self.extension = extension

    @staticmethod
    def get(obj):
        """Gets the revision context associated with a revision. None if not available."""
        if hasattr(obj, '_revision_context'):
            return obj._revision_context
        else:
            return None

    def attach(self, obj):
        """Attaches context to a revision"""
        obj._revision_context = self
