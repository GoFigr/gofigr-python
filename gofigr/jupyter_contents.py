"""\
Copyright (c) 2022, Flagstaff Solutions, LLC
All rights reserved.

Custom Jupyter ContentsManager that auto-injects a ``%load_ext gofigr`` cell
into newly created notebooks.

Enable it by adding the following to a ``jupyter_server_config.py``::

    c.ServerApp.contents_manager_class = "gofigr.jupyter_contents.GoFigrContentsManager"

This only fires on the "new notebook" action; uploaded or pre-existing
notebooks are left untouched.
"""
# redefined-builtin: `type` is part of the ContentsManager.new_untitled signature
# we override. too-many-ancestors: inherited from AsyncLargeFileManager's chain.
# pylint: disable=redefined-builtin, too-many-ancestors

from jupyter_server.services.contents.largefilemanager import AsyncLargeFileManager
from nbformat.v4 import new_code_cell, new_markdown_cell

GOFIGR_MAGIC = "%load_ext gofigr"

GOFIGR_NOTE = (
    "### 📊 GoFigr enabled\n"
    "\n"
    "The cell below loads the GoFigr extension, which automatically captures "
    "the figures you create in this notebook for sharing and reproducibility. "
    "Learn more at [docs.gofigr.io](https://docs.gofigr.io/)."
)


class GoFigrContentsManager(AsyncLargeFileManager):
    """Inserts a ``%load_ext gofigr`` cell at the top of every new notebook."""

    async def new_untitled(self, path="", type="", ext=""):
        model = await super().new_untitled(path=path, type=type, ext=ext)
        if model.get("type") != "notebook":
            return model

        # new_untitled already persisted an empty notebook. Re-fetch it WITH
        # content, inject the cell, and save back as a side effect. We must
        # still return the original content-less model: the POST /api/contents
        # handler validates new_untitled responses with expect_content=False
        # and rejects any model whose content/format keys are not None.
        full = await self.get(model["path"], content=True, type="notebook")
        cells = full["content"]["cells"]

        already_present = any(
            cell.get("source", "").strip().startswith(GOFIGR_MAGIC) for cell in cells
        )
        if not already_present:
            cells.insert(0, new_code_cell(source=GOFIGR_MAGIC))
            cells.insert(0, new_markdown_cell(source=GOFIGR_NOTE))
            await self.save(full, full["path"])
            self.log.info("GoFigrContentsManager: injected '%s' into %s",
                          GOFIGR_MAGIC, full["path"])

        return model
