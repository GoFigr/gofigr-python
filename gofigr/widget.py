"""\
Copyright (c) 2024, Flagstaff Solutions, LLC
All rights reserved.

"""
from abc import ABC
# pylint: disable=trailing-whitespace

from base64 import b64encode
from uuid import uuid4

import humanize
from IPython.core.display import HTML

try:
    from IPython.core.display_functions import display
except ModuleNotFoundError:
    from IPython.core.display import display

from gofigr.utils import read_resource_b64, read_resource_text


BUTTON_STYLE = "padding-top: 0.25em; padding-bottom: 0.25em; padding-left: 0.5em; padding-right: 0.5em; " + \
               "color: #fff; display: inline-block; font-weight: 400; line-height: 1; " + \
               "text-align: center; vertical-align: middle; cursor: pointer; border: 1px solid transparent; " + \
               "font-size: 0.875rem; border-radius: 0.35rem; margin-top: auto; margin-bottom: auto; "

VIEW_BUTTON_STYLE = BUTTON_STYLE + "background-color: #ed6353; border-color: #ed635e; margin-left: 0.5rem; "
DOWNLOAD_BUTTON_STYLE = BUTTON_STYLE + "background-color: #0d53b1; border-color: #0d53b1; margin-left: 0.5rem; "

COPY_BUTTON_STYLE = BUTTON_STYLE + "background-color: #2c7df5; border-color: #2c7df5; margin-left: 0.5rem; "

WIDGET_STYLE = "margin-top: 1rem; margin-bottom: 1rem; margin-left: auto; margin-right: auto;" + \
               "display: flex !important; border: 1px solid transparent; border-color: #cedcef; padding: 0.75em; " + \
               "border-radius: 0.35rem; flex-wrap: wrap; "

COMPACT_WIDGET_STYLE = "margin-top: 1rem; margin-bottom: 1rem; margin-left: auto; margin-right: auto;" + \
               "display: flex !important; border: 1px solid transparent; border-color: #cedcef; padding: 0.25em; " + \
               "padding-top: 0.5em; " + \
               "border-radius: 0.35rem; flex-wrap: wrap; "

MINIMAL_WIDGET_STYLE = "margin-top: 1rem; margin-bottom: 1rem; margin-left: auto; margin-right: auto;" + \
               "display: flex !important; padding: 0.25em; " + \
               "padding-top: 0.5em; flex-wrap: wrap; "

ME2 = "margin-right: 1rem"

MESSAGE_STYLE = "padding-top: 0.25rem; "

ROW_STYLE = "width: 100%; display: flex; flex-wrap: wrap;"

BREAK_STYLE = "flex-basis: 100%; height: 0;"

FA_VIEW = """<svg xmlns="http://www.w3.org/2000/svg" height="0.85rem" width="0.85rem" viewBox="0 0 512 512"><!--!Font 
Awesome Free 6.5.1 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 
2024 Fonticons, Inc.--><path fill="#ffffff" d="M352 0c-12.9 0-24.6 7.8-29.6 19.8s-2.2 25.7 6.9 34.9L370.7 96 201.4 
265.4c-12.5 12.5-12.5 32.8 0 45.3s32.8 12.5 45.3 0L416 141.3l41.4 41.4c9.2 9.2 22.9 11.9 34.9 6.9s19.8-16.6 
19.8-29.6V32c0-17.7-14.3-32-32-32H352zM80 32C35.8 32 0 67.8 0 112V432c0 44.2 35.8 80 80 80H400c44.2 0 80-35.8 
80-80V320c0-17.7-14.3-32-32-32s-32 14.3-32 32V432c0 8.8-7.2 16-16 16H80c-8.8 0-16-7.2-16-16V112c0-8.8 7.2-16 
16-16H192c17.7 0 32-14.3 32-32s-14.3-32-32-32H80z"/></svg>"""

FA_COPY = """<svg xmlns="http://www.w3.org/2000/svg" height="1rem" width="0.85rem" viewBox="0 0 448 512"><!--!Font 
Awesome Free 6.5.1 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 
2024 Fonticons, Inc.--><path fill="#ffffff" d="M208 0H332.1c12.7 0 24.9 5.1 33.9 14.1l67.9 67.9c9 9 14.1 21.2 14.1 
33.9V336c0 26.5-21.5 48-48 48H208c-26.5 0-48-21.5-48-48V48c0-26.5 21.5-48 48-48zM48 128h80v64H64V448H256V416h64v48c0 
26.5-21.5 48-48 48H48c-26.5 0-48-21.5-48-48V176c0-26.5 21.5-48 48-48z"/></svg>"""

FA_COPY_LIGHT = FA_COPY.replace("#ffffff", "#0d53b1")

FA_DOWNLOAD = """<svg xmlns="http://www.w3.org/2000/svg" height="1rem" width="1rem" viewBox="0 0 512 512"><!--!Font 
Awesome Free 6.5.1 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 
2024 Fonticons, Inc.--><path fill="#ffffff" d="M288 32c0-17.7-14.3-32-32-32s-32 14.3-32 
32V274.7l-73.4-73.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3l128 128c12.5 12.5 32.8 12.5 45.3 
0l128-128c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L288 274.7V32zM64 352c-35.3 0-64 28.7-64 64v32c0 35.3 28.7 64 
64 64H448c35.3 0 64-28.7 64-64V416c0-35.3-28.7-64-64-64H346.5l-45.3 45.3c-25 25-65.5 25-90.5 0L165.5 352H64zm368 
56a24 24 0 1 1 0 48 24 24 0 1 1 0-48z"/></svg>"""


def timestamp_to_local_tz(dt_tz):
    """Converts a datetime to the local timezone"""
    return dt_tz.astimezone(tz=None)


class WidgetBase(ABC):
    """Generates HTML/Javascript for the GoFigr Jupyter widget shown under each figure"""

    def __init__(self):
        """

        :param revision: gf.Revision instance
        """
        self._logo_b64 = None

    def get_logo_b64(self):
        """Reads the GoFigr logo and returns it as a base64 string"""
        if self._logo_b64 is not None:
            return self._logo_b64

        self._logo_b64 = read_resource_b64("gofigr.resources", "logo_small.png")
        return self._logo_b64

    def show(self):
        """Displays the widget in Jupyter"""
        raise NotImplementedError


class RevisionWidgetBase(WidgetBase, ABC):
    """Generates HTML/Javascript for the GoFigr Jupyter widget shown under each figure"""

    def __init__(self, revision):
        """

        :param revision: gf.Revision instance
        """
        super().__init__()
        self.revision = revision
        self.id = f"gf-widget-{str(uuid4())}"
        self.alert_id = f"{self.id}-alert"

    def get_download_link(self, label, watermark, image_format="png"):
        """Generates HTML for the download link"""
        matches = [img for img in self.revision.image_data
                   if img.format and img.format.lower() == image_format.lower() and img.is_watermarked == watermark]
        if len(matches) == 0:
            return ""
        else:
            img = matches[0]
            return f"""<a download="{self.revision.figure.name}.{image_format}" 
                          style="{DOWNLOAD_BUTTON_STYLE}"
                          href="data:image/{image_format};base64,{b64encode(img.data).decode('ascii')}">
                          {label}</a>"""

    def _render_template(self, name, mapping):
        """Renders a JavaScript template with the given variable mappings"""
        template = read_resource_text("gofigr.resources", name).replace("\n", "")
        for key, value in mapping.items():
            template = template.replace(key, value)
        template = template.replace("\"", "'")
        return template

    def get_copy_link(self, label, watermark, image_format="png"):
        """Generates HTML/JS for the copy image button"""
        matches = [img for img in self.revision.image_data
                   if img.format and img.format.lower() == image_format.lower() and img.is_watermarked == watermark]
        if len(matches) == 0:
            return ""

        img = matches[0]
        onclick = self._render_template("copy_image.js",
                                        {"_ALERT_ID_": self.alert_id,
                                         "_ERROR_MESSAGE_": "Unable to copy image. "
                                                            "Are you running over HTTPS and/or localhost?",
                                         "_SUCCESS_MESSAGE_": "Image copied to clipboard!",
                                         "_IMAGE_B64_": b64encode(img.data).decode('ascii')})
        return f"""<button onclick="{onclick}" style="{COPY_BUTTON_STYLE}">{label}</button>"""

    def get_text_copy_link(self, label, text):
        """Generates HTML/JS for the copy link button"""
        onclick = read_resource_text("gofigr.resources", "copy_text.js").replace("\n", "")
        onclick = onclick.replace("_TEXT_", text)
        onclick = onclick.replace("_ALERT_ID_", self.alert_id)
        onclick = onclick.replace("_SUCCESS_MESSAGE_", "Link copied to clipboard!")
        onclick = onclick.replace("_ERROR_MESSAGE_", "Unable to copy link. Make sure your Jupyter instance is "
                                                     "running over HTTPS and/or on localhost.")
        onclick = onclick.replace("\"", "'")

        return f"""<span onclick="{onclick}" style="cursor: pointer; color: #0d53b1; ">{label}</span>"""


class DetailedWidget(RevisionWidgetBase):
    """Generates HTML/Javascript for the GoFigr Jupyter widget shown under each figure"""
    def show(self):
        """Renders this widget in Jupyter by generating the HTML/JS & calling display()"""
        logo_b64 = self.get_logo_b64()
        copy_url = self.get_text_copy_link(f"<span style='margin-left: 0.5rem;'>"
                                           f"{self.revision.figure.name}</span>"
                                           f"<span style='margin-left: 0.25rem; margin-right: 0.25rem';>"
                                           f"{FA_COPY_LIGHT}</span>",
                                           self.revision.revision_url)

        logo_html = self.get_text_copy_link(f"""<img src="data:image;base64,{logo_b64}" alt="GoFigr.io logo" 
                style='width: 3rem; height: 3rem'/>""", self.revision.revision_url)

        return display(HTML(f"""
                <div style="{WIDGET_STYLE}">
                    <div style="{ROW_STYLE + "margin-bottom: 0.5rem"}">
                    <span>Successfully published {copy_url} 
                    on {timestamp_to_local_tz(self.revision.created_on).strftime("%x at %X")}.</span> 
                    <span style="margin-left: 0.25rem;"> 
                    Revision size: {humanize.naturalsize(self.revision.size_bytes)}</span>
                    </div>

                    <div style="{ROW_STYLE}">
                    <!-- Logo -->
                    {logo_html}

                    <!-- View on GoFigr -->
                    <a href='{self.revision.revision_url}' target="_blank" style="{VIEW_BUTTON_STYLE}">{FA_VIEW}
                    <span> View on GoFigr</span></a>

                    <!-- Download -->
                    {self.get_download_link(FA_DOWNLOAD + "<span> Download</span>", True, "png")}
                    {self.get_download_link(FA_DOWNLOAD + "<span> Download (no watermark)</span>", False, "png")}

                    <!-- Copy -->
                    {self.get_copy_link(FA_COPY + "<span> Copy</span>", True, "png")}
                    {self.get_copy_link(FA_COPY + "<span> Copy (no watermark)</span>", False, "png")}

                    </div>

                    <div id={self.alert_id} style="{ROW_STYLE + MESSAGE_STYLE}">
                    </div>
                </div>"""))


class CompactWidget(RevisionWidgetBase):
    """Generates a compact GoFigr widget"""

    def show(self):
        """Renders this widget in Jupyter by generating the HTML/JS & calling display()"""
        logo_b64 = self.get_logo_b64()
        logo_html = self.get_text_copy_link(f"""<img src="data:image;base64,{logo_b64}" alt="GoFigr.io logo" 
        style='width: 2rem; height: 2rem'/>""", self.revision.revision_url)

        return display(HTML(f"""
                <div style="{COMPACT_WIDGET_STYLE}">
                    <div style="{ROW_STYLE + "margin-bottom: 0.0rem"}">
                    <!-- Logo -->
                    {logo_html}               

                    <!-- View on GoFigr -->
                    <a href='{self.revision.revision_url}' target="_blank" style="{VIEW_BUTTON_STYLE}">{FA_VIEW}
                    <span> View on GoFigr</span></a>

                    <!-- Download -->
                    {self.get_download_link(FA_DOWNLOAD + "<span> Download</span>", True, "png")}
                    {self.get_download_link(FA_DOWNLOAD + "<span> Download (no watermark)</span>", False, "png")}

                    <!-- Copy -->
                    {self.get_copy_link(FA_COPY + "<span> Copy</span>", True, "png")}
                    {self.get_copy_link(FA_COPY + "<span> Copy (no watermark)</span>", False, "png")}

                    </div>

                    <div id={self.alert_id} style="{ROW_STYLE + MESSAGE_STYLE}">
                    </div>
                </div>"""))


class MinimalWidget(RevisionWidgetBase):
    """Generates a compact GoFigr widget"""

    def show(self):
        """Renders this widget in Jupyter by generating the HTML/JS & calling display()"""
        logo_b64 = self.get_logo_b64()
        logo_html = self.get_text_copy_link(f"""<img src="data:image;base64,{logo_b64}" alt="GoFigr.io logo" 
        style='width: 2rem; height: 2rem; margin-right: 0.5rem;'/>""", self.revision.revision_url)

        return display(HTML(f"""
                <div style="{COMPACT_WIDGET_STYLE}">
                    <div style="{ROW_STYLE + "margin-bottom: 0.0rem"}">
                    <!-- Logo -->
                    {logo_html}               

                    <!-- View on GoFigr -->
                    <a href='{self.revision.revision_url}' target="_blank" style="margin-top: auto; margin-bottom: auto;">View on GoFigr</a>
                    </div>
                    
                    <div id={self.alert_id} style="{ROW_STYLE + MESSAGE_STYLE}">
                    </div>
                </div>"""))


class StartupWidget(WidgetBase):
    """Generates a GoFigr startup widget"""
    def __init__(self, extension):
        super().__init__()
        self.extension = extension

    def get_link(self, obj):
        """Gets the app link to a GoFigr object"""
        return f"""<a style="margin-left: 0.25em" href={obj.app_url}>{obj.name}</a>"""

    def show(self):
        """Renders this widget in Jupyter by generating the HTML/JS & calling display()"""
        logo_b64 = self.get_logo_b64()
        logo_html = f"""<img src="data:image;base64,{logo_b64}" alt="GoFigr.io logo" 
            style='width: 2rem; height: 2rem; margin-right: 0.5rem;'/>"""

        return display(HTML(f"""
                    <div style="{WIDGET_STYLE}">
                        <div style="{ROW_STYLE + "margin-bottom: 0.0rem"}">
                            <!-- Logo -->
                            {logo_html}      
                            
                            <div style="margin-top: auto; margin-bottom: auto;">
                                <span style="font-weight: bold">GoFigr active</span>. 
                                Workspace: {self.get_link(self.extension.publisher.workspace)}. 
                                Analysis: {self.get_link(self.extension.publisher.analysis)}. 
                                Autopublish: {self.extension.auto_publish}.
                            </div>
                        </div>
                        
                    </div>"""))


class AssetWidget(WidgetBase):
    """Generates a GoFigr startup widget"""
    def __init__(self, rev):
        super().__init__()
        self.rev = rev

    def get_link(self, obj):
        """Gets the app link to a GoFigr object"""
        if not obj.asset.name:
            obj.asset.fetch()
        return f"""<a style="margin-left: 0.25em" href={obj.app_url}>{obj.asset.name}</a>"""

    def show(self):
        """Renders this widget in Jupyter by generating the HTML/JS & calling display()"""
        logo_b64 = self.get_logo_b64()
        logo_html = f"""<img src="data:image;base64,{logo_b64}" alt="GoFigr.io logo" 
            style='width: 2rem; height: 2rem; margin-right: 0.5rem;'/>"""

        return display(HTML(f"""
                    <div style="{WIDGET_STYLE}">
                        <div style="{ROW_STYLE + "margin-bottom: 0.0rem"}">
                            <!-- Logo -->
                            {logo_html}      

                            <div style="margin-top: auto; margin-bottom: auto;">
                                <span style="font-weight: bold">Asset: </span>
                                {self.get_link(self.rev)} {"(new revision)" if self.rev.is_new_revision else "(existing revision)"}.
                            </div>
                        </div>

                    </div>"""))
