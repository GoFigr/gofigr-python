"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import io
import os
import re
import subprocess
import time
from argparse import ArgumentParser
from datetime import datetime

import selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By


def find_element_with_alternatives(driver, by, possible_values):
    """Calls driver.find_element using alternative names until the element is found, or raises an exception"""
    for val in possible_values:
        try:
            return driver.find_element(by=by, value=val)
        except selenium.common.exceptions.NoSuchElementException:
            continue  # try next possible value

    raise RuntimeError(f"No such element.Tried: " + ", ".join(possible_values))


def retry(runnable, max_retries):
    for attempt in range(max_retries):
        print(f"Attempt {attempt}...")
        try:
            return runnable()
        except Exception as e:
            print(e)
            continue

    raise RuntimeError(f"Execution failed despite {max_retries} retries")

def run_notebook(driver, jupyter_url):
    if '/tree' in jupyter_url:
        # Running Notebook 7
        driver.get(jupyter_url.replace("/tree?token=", "/notebooks/integration_tests.ipynb?factory=Notebook&token="))
    else:
        driver.get(jupyter_url.replace("?token=", "notebooks/integration_tests.ipynb?token="))

    try:
        # For Jupyter Notebook 6.x
        driver.find_element(by=By.CSS_SELECTOR, value="#kernellink").click()
        driver.find_element(by=By.CSS_SELECTOR, value="#restart_run_all").click()
    except selenium.common.exceptions.NoSuchElementException:
        # For Jupyter Notebook 5.x
        find_element_with_alternatives(driver, by=By.CSS_SELECTOR,
                                       possible_values=[
                                           'button[data-jupyter-action="jupyter-notebook:confirm-restart-kernel-and-run-all-cells"]',
                                           "button[data-command='runmenu:restart-and-run-all']"
                                       ]).click()
    # Confirm
    find_element_with_alternatives(driver, by=By.CSS_SELECTOR,
                                   possible_values=[".modal-dialog button.btn.btn-danger",
                                                    ".jp-Dialog-button.jp-mod-warn"]).click()


def run_lab(driver, jupyter_url):
    driver.get(jupyter_url.replace("/lab?token=", "/lab/tree/integration_tests.ipynb?token="))

    # Restart and run all button
    driver.find_element(by=By.CSS_SELECTOR, value="button[data-command='runmenu:restart-and-run-all']").click()

    # Confirm
    driver.find_element(by=By.CSS_SELECTOR, value=".jp-Dialog-button.jp-mod-warn").click()


def main():
    parser = ArgumentParser(description="Uses Selenium to run a Jupyter notebook inside a Notebook/Lab server"
                                        " instance.")
    parser.add_argument("service", help="notebook or lab")
    parser.add_argument("notebook_path", help="Path to ipynb notebook")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Timeout in seconds (max 300s) for the notebook to finish execution")
    parser.add_argument("--retries", type=int, default=5,
                        help="Maximum number of ties to retry execution. The tests are flaky due to Selenium not "
                             "being able to find UI elements or them not loading in time.")
    args = parser.parse_args()

    working_dir = os.path.dirname(args.notebook_path)
    filename = os.path.join(working_dir, "driver.log")
    with io.open(filename, "w") as writer, io.open(filename, "r", 1) as reader:
        proc = subprocess.Popen(["jupyter", args.service, "--no-browser", args.notebook_path],
                                stdout=writer,
                                stderr=writer)

        driver = None
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
            driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()))
            driver.implicitly_wait(30.0)

            if args.service == "notebook":
                retry(lambda: run_notebook(driver, jupyter_url), args.retries)
            elif args.service == "lab":
                retry(lambda: run_lab(driver, jupyter_url), args.retries)
            else:
                raise ValueError(f"Unsupported service: {args.service}")

            start_time = datetime.now()
            timed_out = True
            while (datetime.now() - start_time).total_seconds() < args.timeout:
                if os.path.exists(output_path + ".done"):
                    timed_out = False
                    break

                time.sleep(1)

            if timed_out:
                raise RuntimeError("Execution timed out.")

            print(f"Finished after {(datetime.now() - start_time).total_seconds():.2f} seconds")

        finally:
            proc.terminate()

            if driver is not None:
                driver.close()


if __name__ == "__main__":
    main()
