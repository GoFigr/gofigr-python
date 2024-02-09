"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import datetime
import json
import os
import shutil
import subprocess
import sys
from argparse import ArgumentParser

from teamcity.messages import TeamcityServiceMessages

from gofigr import GoFigr
from gofigr.jupyter import from_config_or_env


@from_config_or_env("GF_", os.path.join(os.environ['HOME'], '.gofigr'))
def get_gf(test_user, test_password):
    return GoFigr(username=test_user, password=test_password, url="https://api-dev.gofigr.io")


def clean_up():
    gf = get_gf()

    ana = gf.primary_workspace.get_analysis("Integration tests", create=True).fetch()
    print("Cleaning up....")
    for fig in ana.figures:
        fig.fetch()
        for rev in fig.revisions:
            rev.delete(delete=True)

        fig.delete(delete=True)

    print("Cleanup complete.")


def format_cmd(args):
    """Formats command line arguments."""
    def format_one(x):
        if ' ' in x:
            return f'"{x}"'
        else:
            return x

    return " ".join([format_one(x) for x in args])


def run_one_config(args, idx, config, all_configurations, messages):
    """Runs a single configuration"""
    run_one = os.path.join(os.path.dirname(sys.argv[0]), "run_one.sh")
    out_dir = os.path.join(args.output, config["name"])

    print(f"Running configuration {idx + 1}/{len(all_configurations)}: ")
    print(f'  * Name: {config["name"]}')
    print(f"  * Python: {config['python']}")
    print(f"  * Dependencies: {config['dependencies']}")
    print(f"  * Directory: {out_dir}")

    if os.path.exists(out_dir):
        if args.force:
            shutil.rmtree(out_dir)
        else:
            print("  => Path exists. Skipping\n")
            messages.testIgnored(config["name"], flowId=config["name"])
            return True

    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "config.json"), 'w') as f:
        json.dump(config, f)

    runner_args = ["bash", run_one, out_dir, os.path.join(out_dir, "driver.log"),
                   config["python"], config["service"], config["dependencies"]]
    print(f"  => Running {format_cmd(runner_args)}")
    cp = subprocess.run(runner_args)
    if cp.returncode != 0:
        print(f"  => Process failed with code {cp.returncode}")
        return False

        with open(os.path.join(out_dir, "errors.json"), 'w') as ef:
            json.dump({"error": None if cp.stderr is None else cp.stderr.decode('ascii', errors='ignore')}, ef)

    else:
        print("  => Complete")
        return True


def main():
    parser = ArgumentParser(description="Runs integration tests based on a config file")
    parser.add_argument("config", help="config file (JSON)")
    parser.add_argument("output", help="output directory")
    parser.add_argument("--force", action="store_true", help="Force re-run even if directory already exists")
    args = parser.parse_args()

    with open(args.config, "r") as f:
        all_configurations = json.load(f)

        if isinstance(all_configurations, dict):
            all_configurations = [all_configurations]

    messages = TeamcityServiceMessages()
    messages.testSuiteStarted("Compatibility checks")
    messages.testCount(len(all_configurations))

    for idx, config in enumerate(all_configurations):
        start_time = datetime.datetime.now()
        try:
            messages.testStarted(config["name"], flowId=config["name"])
            clean_up()
            success = run_one_config(args, idx, config, all_configurations, messages)
            if not success:
                messages.testFailed(config["name"], flowId=config["name"])
        except Exception as e:  # pylint: disable=broad-exception-caught
            messages.testFailed(config["name"], message=str(e), flowId=config["name"])
        finally:
            clean_up()
            messages.testFinished(config["name"], testDuration=datetime.datetime.now() - start_time, flowId=config["name"])

    messages.testSuiteFinished("Compatibility checks")

if __name__ == "__main__":
    main()
