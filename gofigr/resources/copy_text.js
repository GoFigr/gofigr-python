navigator.clipboard.writeText("_TEXT_")
            .then(() => {
                document.getElementById("_ALERT_ID_").innerHTML = "_SUCCESS_MESSAGE_";
                setTimeout(() => {document.getElementById("_ALERT_ID_").innerHTML = "";}, 1000);
            })
            .catch(err => {
                document.getElementById("_ALERT_ID_").innerHTML = "_ERROR_MESSAGE_";
                setTimeout(() => {document.getElementById("_ALERT_ID_").innerHTML = "";}, 4000);
            });
