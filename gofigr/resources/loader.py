"""\
Copyright (c) 2022-2025, Flagstaff Solutions, LLC
All rights reserved.

"""

# pylint: disable=wildcard-import, unused-wildcard-import, undefined-variable

from gofigr.jupyter import *
get_ipython().run_line_magic('load_ext', 'gofigr')
configure(analysis=NotebookName())
