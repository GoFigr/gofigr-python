/**
 * Reproducible Widget JavaScript
 *
 * Provides interactive controls for @reproducible decorated functions.
 * Supports: sliders, checkboxes, dropdowns, and text inputs.
 */
export function render({ model, el }) {
  const container = document.createElement("div");
  container.style.cssText = "padding: 12px; border: 1px solid #ddd; border-radius: 8px; background: #f9f9f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;";

  const title = document.createElement("h4");
  title.innerText = "Reproducible Controls";
  title.style.cssText = "margin: 0 0 12px 0; color: #333; font-size: 14px;";
  container.appendChild(title);

  const params = model.get("params");
  const paramMeta = model.get("param_meta");

  function updateParam(key, value) {
    const currentParams = {...model.get("params")};
    currentParams[key] = value;
    model.set("params", currentParams);
    model.save_changes();
  }

  for (const [key, meta] of Object.entries(paramMeta)) {
    if (meta.type === "static") continue;

    const row = document.createElement("div");
    row.style.cssText = "margin-bottom: 10px; display: flex; align-items: center; gap: 8px;";

    const label = document.createElement("label");
    label.innerText = key + ":";
    label.style.cssText = "min-width: 100px; font-size: 13px; color: #555;";
    row.appendChild(label);

    if (meta.type === "slider") {
      const input = document.createElement("input");
      input.type = "range";
      input.min = meta.min;
      input.max = meta.max;
      input.step = meta.step;
      input.value = params[key];
      input.style.cssText = "flex: 1; max-width: 200px;";

      const valueDisplay = document.createElement("span");
      valueDisplay.innerText = params[key];
      valueDisplay.style.cssText = "min-width: 50px; font-size: 13px; color: #333;";

      input.oninput = (e) => {
        const newVal = meta.step === 1 ? parseInt(e.target.value) : parseFloat(e.target.value);
        valueDisplay.innerText = newVal;
        updateParam(key, newVal);
      };

      row.appendChild(input);
      row.appendChild(valueDisplay);

    } else if (meta.type === "checkbox") {
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = params[key];
      input.style.cssText = "width: 18px; height: 18px;";

      input.onchange = (e) => {
        updateParam(key, e.target.checked);
      };

      row.appendChild(input);

    } else if (meta.type === "dropdown") {
      const select = document.createElement("select");
      select.style.cssText = "padding: 4px 8px; font-size: 13px; border: 1px solid #ccc; border-radius: 4px;";

      for (const choice of meta.choices) {
        const option = document.createElement("option");
        option.value = choice;
        option.text = choice;
        option.selected = params[key] === choice;
        select.appendChild(option);
      }

      select.onchange = (e) => {
        updateParam(key, e.target.value);
      };

      row.appendChild(select);

    } else if (meta.type === "text") {
      const input = document.createElement("input");
      input.type = "text";
      input.value = params[key];
      input.style.cssText = "padding: 4px 8px; font-size: 13px; border: 1px solid #ccc; border-radius: 4px; flex: 1; max-width: 200px;";

      let debounceTimer;
      input.oninput = (e) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          updateParam(key, e.target.value);
        }, 300);
      };

      row.appendChild(input);
    }

    container.appendChild(row);
  }

  el.appendChild(container);
}
