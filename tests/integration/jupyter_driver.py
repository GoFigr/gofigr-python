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
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By


def find_element_with_alternatives(driver, by, possible_values, delay_seconds=0.1, max_wait_seconds=5):
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


def run_notebook(driver, jupyter_url):
    """Runs a notebook in the classic notebook UI"""
    print("Running classic notebook...")

    if '/tree' in jupyter_url:
        # Running Notebook 7
        nav_url = jupyter_url.replace("/tree?token=", "/notebooks/integration_tests.ipynb?factory=Notebook&token=")
    else:
        nav_url = jupyter_url.replace("?token=", "notebooks/integration_tests.ipynb?token=")

    driver.get(nav_url)
    print(f"Navigating to {nav_url}...")

    try:
        # For Jupyter Notebook 6.x
        find_element_with_alternatives(driver, by=By.CSS_SELECTOR, possible_values=["#kernellink"]).click()
        find_element_with_alternatives(driver, by=By.CSS_SELECTOR, possible_values=["#restart_run_all"]).click()
    except RuntimeError:
        # For Jupyter Notebook 5.x or 7.0+
        find_element_with_alternatives(driver, by=By.CSS_SELECTOR,
                                       possible_values=[
                                           'button[data-jupyter-action="jupyter-notebook:confirm-restart-kernel-and-run-all-cells"]',
                                           "button[data-command='runmenu:restart-and-run-all']",
                                           "button[data-command='notebook:restart-run-all']",
                                           "jp-button[data-command='runmenu:restart-and-run-all']",
                                           "jp-button[data-command='notebook:restart-run-all']",
                                       ]).click()

    # Confirm
    print("Confirming...")
    try:
        find_element_with_alternatives(driver, by=By.CSS_SELECTOR,
                                       possible_values=[".modal-dialog button.btn.btn-danger",
                                                        ".jp-Dialog-button.jp-mod-warn"]).click()
    except RuntimeError:
        # For some reason Jupyter doesn't prompt for confirmation on Linux
        driver.save_screenshot("confirmation_failed.png")
        print("Confirmation failed, but continuing anyway...")

    print("UI done. Waiting for execution...")


def run_lab(driver, jupyter_url):
    driver.get(jupyter_url.replace("/lab?token=", "/lab/tree/integration_tests.ipynb?token="))

    # Restart and run all button
    find_element_with_alternatives(driver, by=By.CSS_SELECTOR, possible_values=[
        "button[data-command='runmenu:restart-and-run-all']",
        "button[data-command='notebook:restart-run-all']",
        "jp-button[data-command='runmenu:restart-and-run-all']",
        "jp-button[data-command='notebook:restart-run-all']"
    ]).click()

    # Confirm
    find_element_with_alternatives(driver, by=By.CSS_SELECTOR, possible_values=[
        ".jp-Dialog-button.jp-mod-warn"
    ]).click()


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
        if args.headless:
            opts.add_argument('--headless=new')

        print(f"Headless: {args.headless}")
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()),
                                  options=opts)
        driver.implicitly_wait(5.0)

        if args.service == "notebook":
            run_notebook(driver, jupyter_url)
        elif args.service == "lab":
            run_lab(driver, jupyter_url)
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
    parser.add_argument("--timeout", type=int, default=600,
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

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
