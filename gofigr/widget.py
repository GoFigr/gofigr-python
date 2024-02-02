"""\
Copyright (c) 2024, Flagstaff Solutions, LLC
All rights reserved.

"""
from base64 import b64encode

import humanize
from IPython.core.display import HTML
from IPython.core.display_functions import display

from gofigr.utils import read_resource_b64

"""
const link = document.createElement('a');
                link.href = `data:image/${obj.metadata.format};base64,${result.data}`;
                link.download = props.downloadName + "." + obj.metadata.format;
                link.click();
                """


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


class GoFigrWidget:
    def __init__(self, revision):
        self.revision = revision
        self._logo_b64 = None

    def get_logo_b64(self):
        if self._logo_b64 is not None:
            return self._logo_b64

        self._logo_b64 = read_resource_b64("gofigr.resources", "logo_small.png")
        return self._logo_b64

    def get_download_link(self, label, watermark, image_format="png"):
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

    def get_copy_link(self, label, watermark, image_format="png"):
        matches = [img for img in self.revision.image_data
                   if img.format and img.format.lower() == image_format.lower() and img.is_watermarked == watermark]
        if len(matches) == 0:
            return ""
        else:
            img = matches[0]
            return f"""<button style="{COPY_BUTTON_STYLE}">{label}</button>"""

    def show(self):
        logob64 = self.get_logo_b64()

        return display(HTML(f"""
            <div style="{WIDGET_STYLE}">
                <div style="{ROW_STYLE + "margin-bottom: 0.5rem"}">
                <span>Successfully published "{self.revision.figure.name}" on {timestamp_to_local_tz(self.revision.created_on).strftime("%x at %X")}.</span> 
                <span style="margin-left: 0.25rem;"> Revision size: {humanize.naturalsize(self.revision.size_bytes)}</span>
                </div>
                            
                <div style="{ROW_STYLE}">
                <!-- Logo -->
                <img src="data:image;base64,{logob64}" alt="GoFigr.io logo" style='width: 3em; height: 3em'/>
                
                <!-- View on GoFigr -->
                <a href='{self.revision.revision_url}' target="_blank" style="{VIEW_BUTTON_STYLE}">{FA_VIEW}<span> View on GoFigr</span></a>
                
                <!-- Download -->
                {self.get_download_link(FA_DOWNLOAD + "<span> Download</span>", True, "png")}
                {self.get_download_link(FA_DOWNLOAD + "<span> Download (no watermark)</span>", False, "png")}
                
                <!-- Copy -->
                {self.get_copy_link(FA_COPY + "<span> Copy</span>", True, "png")}
                {self.get_copy_link(FA_COPY + "<span> Copy (no watermark)</span>", False, "png")}
                
                </div>
            </div>"""))
