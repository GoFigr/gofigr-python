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


def find_element_with_alternatives(driver, by, possible_values):
    """Calls driver.find_element using alternative names until the element is found, or raises an exception"""
    for val in possible_values:
        try:
            return driver.find_element(by=by, value=val)
        except selenium.common.exceptions.NoSuchElementException:
            continue  # try next possible value

    raise RuntimeError(f"No such element. Tried: " + ", ".join(possible_values))


def run_notebook(driver, jupyter_url):
    """Runs a notebook in the classic notebook UI"""
    print("Running classic notebook...")

    if '/tree' in jupyter_url:
        # Running Notebook 7
        driver.get(jupyter_url.replace("/tree?token=", "/notebooks/integration_tests.ipynb?factory=Notebook&token="))
    else:
        driver.get(jupyter_url.replace("?token=", "notebooks/integration_tests.ipynb?token="))

    print("Waiting for navigate...")
    time.sleep(10)

    try:
        # For Jupyter Notebook 6.x
        driver.find_element(by=By.CSS_SELECTOR, value="#kernellink").click()
        time.sleep(5)
        driver.find_element(by=By.CSS_SELECTOR, value="#restart_run_all").click()
        time.sleep(5)
    except selenium.common.exceptions.NoSuchElementException:
        # For Jupyter Notebook 5.x
        find_element_with_alternatives(driver, by=By.CSS_SELECTOR,
                                       possible_values=[
                                           'button[data-jupyter-action="jupyter-notebook:confirm-restart-kernel-and-run-all-cells"]',
                                           "button[data-command='runmenu:restart-and-run-all']"
                                       ]).click()
        time.sleep(5)

    # Confirm
    print("Confirming...")
    find_element_with_alternatives(driver, by=By.CSS_SELECTOR,
                                   possible_values=[".modal-dialog button.btn.btn-danger",
                                                    ".jp-Dialog-button.jp-mod-warn"]).click()
    time.sleep(5)

    print("UI done. Waiting for execution...")


def run_lab(driver, jupyter_url):
    driver.get(jupyter_url.replace("/lab?token=", "/lab/tree/integration_tests.ipynb?token="))

    time.sleep(10)

    # Restart and run all button
    driver.find_element(by=By.CSS_SELECTOR, value="button[data-command='runmenu:restart-and-run-all']").click()
    time.sleep(5)

    # Confirm
    driver.find_element(by=By.CSS_SELECTOR, value=".jp-Dialog-button.jp-mod-warn").click()
    time.sleep(5)


def run_attempt(args, working_dir, reader, writer):
    proc = subprocess.Popen(["jupyter", args.service, "--no-browser", args.notebook_path],
                            stdout=writer,
                            stderr=writer)

    driver = None
    success = False
    try:
        jupyter_url = None
        while proc.poll() is None and jupyter_url is None:
            line = reader.readline()
            m = re.match(r'.*(http.*\?token=\w+).*', line)
            if m is not None:
                jupyter_url = m.group(1)

            time.sleep(0.5)

        output_path = os.path.join(working_dir, "integration_test.json")
        if os.path.exists(output_path):
            os.remove(output_path)
            print(f"Deleted {output_path}")

        print(f"URL: {jupyter_url}")
        time.sleep(5)

        print("Starting Chrome...")
        opts = Options()
        if args.headless:
            opts.add_argument('--headless=new')

        print(f"Headless: {args.headless}")
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()),
                                  options=opts)
        driver.implicitly_wait(30.0)

        if args.service == "notebook":
            run_notebook(driver, jupyter_url)
        elif args.service == "lab":
            run_lab(driver, jupyter_url)
        else:
            raise ValueError(f"Unsupported service: {args.service}")

        start_time = datetime.now()
        timed_out = True
        while (datetime.now() - start_time).total_seconds() < args.timeout:
            if os.path.exists(output_path + ".done"):
                timed_out = False
                success = True
                break

            time.sleep(1)

        if timed_out:
            print("Execution timed out.")
    except:
        traceback.print_exc()
        print("Execution failed")
    finally:
        if driver is not None:
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
    parser.add_argument("--timeout", type=int, default=300,
                        help="Timeout in seconds (max 300s) for the notebook to finish execution")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--retries", type=int, default=5,
                        help="Maximum number of execution attempts. The tests are flaky due to Selenium not "
                             "being able to find UI elements or them not loading in time.")
    args = parser.parse_args()

    working_dir = os.path.dirname(args.notebook_path)
    filename = os.path.join(working_dir, "jupyter.log")

    attempt = 0
    success = False
    with io.open(filename, "w") as writer, io.open(filename, "r", 1) as reader:
        while attempt < args.retries and not success:
            print(f"Running attempt {attempt + 1}...")
            success = run_attempt(args, working_dir, reader, writer)
            attempt += 1

    status = "Succeeded" if success else "Failed"
    print(f"{status} after {attempt} attempts.")

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
