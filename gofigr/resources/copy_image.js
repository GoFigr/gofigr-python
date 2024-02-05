const dataURL = "data:image/png;base64,_IMAGE_B64_";
fetch(dataURL).then(res => res.blob()).then(blob_data => {
    navigator.clipboard.write([new ClipboardItem({"image/png": blob_data})])
        .then(() => {
            document.getElementById("_ALERT_ID_").innerHTML = "_SUCCESS_MESSAGE_";
            setTimeout(() => {
                document.getElementById("_ALERT_ID_").innerHTML = "";
            }, 1000);
        })
        .catch(err => {
            console.log(err);
            document.getElementById("_ALERT_ID_").innerHTML = "_ERROR_MESSAGE_";
            setTimeout(() => {
                document.getElementById("_ALERT_ID_").innerHTML = "";
            }, 4000);
        });
}).catch(err => {
    console.log(err);
            document.getElementById("_ALERT_ID_").innerHTML = "_ERROR_MESSAGE_";
            setTimeout(() => {
                document.getElementById("_ALERT_ID_").innerHTML = "";
            }, 4000);
})