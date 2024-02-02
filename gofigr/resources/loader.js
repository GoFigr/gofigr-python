console.log("GoFigr Javascript proxy started");

let xhr = new XMLHttpRequest();
xhr.open("POST", endpoint);
xhr.setRequestHeader("Accept", "application/json");
xhr.setRequestHeader("Content-Type", "application/json");

xhr.onreadystatechange = function () {
  if (xhr.readyState === XMLHttpRequest.DONE) {
    console.log("Metadata submitted. Response: " + xhr.status + " - " + xhr.responseText);
  }};

let data = {
  metadata: {url: document.URL}
};

xhr.send(JSON.stringify(data));

// Load CSS
document.getElementsByTagName('head')[0].insertAdjacentHTML(
   'beforeend',
    '<link href="data:text/css;base64,' + gofigr_css + '" rel="stylesheet"/>'
   );
