"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import io
import os
import re
import subprocess
import sys
import time
import traceback
from argparse import ArgumentParser
from datetime import datetime

import selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import wait, expected_conditions
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

def find_element_with_alternatives(driver, by, possible_values, delay_seconds=0.5, max_wait_seconds=30):
    """Calls driver.find_element using alternative names until the element is found, or raises an exception"""
    print(f"Looking for {possible_values}")

    start_time = datetime.now()
    while (datetime.now() - start_time).total_seconds() < max_wait_seconds:
        for val in possible_values:
            try:
                elt = driver.find_element(by=by, value=val)
                print(f"  => Found {val}")
                return elt
            except selenium.common.exceptions.NoSuchElementException:
                time.sleep(delay_seconds)
                continue  # try next possible value

    raise RuntimeError(f"No such element. Tried: " + ", ".join(possible_values))


def _trigger_run_all_via_keyboard(driver, is_lab=True):
    """Trigger 'restart and run all cells' using keyboard shortcuts.
    This is more stable across JupyterLab/Notebook versions than relying on internal JS APIs.

    Keyboard shortcuts:
    - JupyterLab: Varies by version, but we can use the Run menu or command palette
    - Classic Notebook: Uses the Jupyter.notebook API which is stable
    """
    # For classic Notebook, the JS API is still reliable and exposed
    if not is_lab:
        js = (
            "var cb = arguments[arguments.length - 1];\n"
            "try {\n"
            "  if (window.Jupyter && window.Jupyter.notebook) {\n"
            "    if (typeof window.Jupyter.notebook.restart_run_all === 'function') {\n"
            "      window.Jupyter.notebook.restart_run_all();\n"
            "    } else {\n"
            "      window.Jupyter.notebook.kernel.restart();\n"
            "      setTimeout(() => { window.Jupyter.notebook.execute_all_cells(); }, 2000);\n"
            "    }\n"
            "    cb('classic_ok');\n"
            "  } else {\n"
            "    cb('error: Jupyter.notebook not found');\n"
            "  }\n"
            "} catch (err) {\n"
            "  cb('error:' + (err && err.message ? err.message : String(err)));\n"
            "}\n"
        )
        result = driver.execute_async_script(js)
        print(f"Classic notebook JS result: {result}")
        if isinstance(result, str) and result.startswith('error'):
            raise RuntimeError(result)
        return

    # For JupyterLab, use keyboard shortcut to open command palette and execute command
    # This works across all JupyterLab versions (3.x, 4.x)
    print("Triggering restart-and-run-all via keyboard shortcut...")

    # Focus the notebook by clicking on it first
    try:
        # Click on the notebook content area to ensure it has focus
        notebook_area = driver.find_element(By.CSS_SELECTOR, '.jp-Notebook')
        notebook_area.click()
        time.sleep(0.5)
    except:
        print("Could not click notebook area, trying to focus body...")
        driver.find_element(By.TAG_NAME, 'body').click()
        time.sleep(0.5)

    # Use ActionChains to send keyboard shortcut
    # Open command palette: Cmd+Shift+C (Mac) or Ctrl+Shift+C (Linux/Windows)
    actions = ActionChains(driver)

    # Determine if we're on Mac or not
    platform = driver.execute_script("return navigator.platform;")
    is_mac = 'Mac' in platform

    modifier_key = Keys.COMMAND if is_mac else Keys.CONTROL

    # Open command palette
    actions.key_down(modifier_key).key_down(Keys.SHIFT).send_keys('c').key_up(Keys.SHIFT).key_up(modifier_key).perform()
    time.sleep(1)

    # Type the command
    actions.send_keys('Restart Kernel and Run All Cells').perform()
    time.sleep(0.5)

    # Press Enter to execute
    actions.send_keys(Keys.ENTER).perform()
    time.sleep(1)

    # Confirm the restart (if dialog appears)
    # The confirmation is usually Enter or clicking a button
    try:
        # Try to find and click the confirm button
        confirm_button = WebDriverWait(driver, 3).until(
            expected_conditions.element_to_be_clickable((By.CSS_SELECTOR, '.jp-Dialog-button.jp-mod-accept'))
        )
        confirm_button.click()
        print("Clicked confirmation dialog")
    except:
        # If no dialog or it's keyboard-accessible, just press Enter
        try:
            actions.send_keys(Keys.ENTER).perform()
            print("Sent Enter for confirmation")
        except:
            print("No confirmation needed or already confirmed")

    time.sleep(1)
    print("Restart-and-run-all triggered successfully")


def run_notebook(driver, jupyter_url, notebook_path):
    """Runs a notebook in the classic notebook UI"""
    print("Running classic notebook...")

    if '/tree' in jupyter_url:
        # Running Notebook 7
        nav_url = jupyter_url.replace("/tree?token=", f"/notebooks/{notebook_path}?factory=Notebook&token=")
    else:
        nav_url = jupyter_url.replace("?token=", f"notebooks/{notebook_path}?token=")

    driver.get(nav_url)
    print(f"Navigating to {nav_url}...")

    WebDriverWait(driver, 120).until(expected_conditions.visibility_of_element_located((By.ID,
                                             "Integration-tests-for-the-GoFigr-Python-client")))

    # Use keyboard/JS approach instead of fragile UI selectors
    _trigger_run_all_via_keyboard(driver, is_lab=False)

    print("UI done. Waiting for execution...")


def run_lab(driver, jupyter_url, notebook_path):
    driver.get(jupyter_url.replace("/lab?token=", f"/lab/tree/{notebook_path}?token="))

    WebDriverWait(driver, 120).until(expected_conditions.visibility_of_element_located((By.CSS_SELECTOR,
                                             '[data-jupyter-id="Integration-tests-for-the-GoFigr-Python-client"]')))

    # Use keyboard shortcuts for Lab (stable across versions)
    _trigger_run_all_via_keyboard(driver, is_lab=True)


def run_attempt(args, working_dir, reader, writer, attempt):
    proc = subprocess.Popen(["jupyter", args.service, "--no-browser", args.notebook_path],
                            stdout=writer,
                            stderr=writer)

    start_time = datetime.now()
    timed_out = True

    driver = None
    success = False
    try:
        jupyter_url = None
        while proc.poll() is None and jupyter_url is None:
            line = reader.readline()
            m = re.match(r'.*(http.*\?token=\w+).*', line)
            if m is not None:
                jupyter_url = m.group(1)
            elif "/tree" in line:
                raise RuntimeError("Found a URL but not a token. Are you using password authentication?")

            if (datetime.now() - start_time).total_seconds() >= args.timeout:
                raise RuntimeError("Timed out")

            time.sleep(0.5)

        output_path = os.path.join(working_dir, "integration_test.json")
        if os.path.exists(output_path):
            os.remove(output_path)
            print(f"Deleted {output_path}")

        if jupyter_url is None:
            raise RuntimeError("Jupyter URL unavailable. Did it start correctly?")

        print(f"URL: {jupyter_url}")
        time.sleep(2)

        print("Starting Chrome...")
        opts = Options()
        opts.add_argument('--window-size=1920,10000')
        if args.headless:
            opts.add_argument('--headless=new')

        print(f"Headless: {args.headless}")
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()),
                                  options=opts)
        driver.implicitly_wait(5.0)

        if args.service == "notebook":
            run_notebook(driver, jupyter_url, args.notebook_path)
        elif args.service == "lab":
            run_lab(driver, jupyter_url, args.notebook_path)
        else:
            raise ValueError(f"Unsupported service: {args.service}")

        while (datetime.now() - start_time).total_seconds() < args.timeout:
            if os.path.exists(output_path + ".done"):
                timed_out = False
                success = True
                break

            time.sleep(1)

        if timed_out:
            print("Execution timed out.", file=sys.stderr)
    except:
        traceback.print_exc()
        print("Execution failed", file=sys.stderr)
    finally:
        if driver is not None:
            driver.save_screenshot(os.path.join(working_dir, f"screenshot_attempt{attempt}.png"))

            with open(os.path.join(working_dir, f"attempt{attempt}.html"), 'w') as f:
                f.write(driver.page_source)

            driver.close()
            time.sleep(5)

        proc.terminate()
        time.sleep(5)

        return success


def main():
    parser = ArgumentParser(description="Uses Selenium to run a Jupyter notebook inside a Notebook/Lab server"
                                        " instance.")
    parser.add_argument("service", help="notebook or lab")
    parser.add_argument("notebook_path", help="Path to ipynb notebook")
    parser.add_argument("--timeout", type=int, default=60*15,
                        help="Timeout in seconds for the notebook to finish execution")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--retries", type=int, default=2, help="Maximum number of execution attempts.")
    args = parser.parse_args()

    working_dir = os.path.dirname(args.notebook_path)
    attempt = 0
    success = False
    while attempt < args.retries and not success:
        print(f"Running attempt {attempt + 1}...")
        filename = os.path.join(working_dir, f"jupyter_attempt{attempt + 1}.log")

        with io.open(filename, "w") as writer, \
                io.open(filename, "r", 1) as reader:
            success = run_attempt(args, working_dir, reader, writer, attempt + 1)
            attempt += 1

    status = "Succeeded" if success else "Failed"
    print(f"{status} after {attempt} attempts.")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
