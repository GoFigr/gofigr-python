"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import concurrent
import datetime
import json
import os
import shutil
import subprocess
import sys
from argparse import ArgumentParser

from teamcity.messages import TeamcityServiceMessages

from gofigr import GoFigr, find_config, FindByName
from gofigr.utils import from_config_or_env


@from_config_or_env("GF_", find_config())
def get_gf(test_user, test_password):
    gf = GoFigr(username=test_user, password=test_password, api_key=None, url="https://api-dev.gofigr.io")
    if "api-dev" not in gf.api_url:
        raise RuntimeError("Running against production. Stopping.")
    return gf


def clean_up(analysis=None, clean_assets=False):
    gf = get_gf()

    worx = gf.find_workspace(FindByName("Integration tests", create=True))
    worx.fetch()

    if analysis:
        analyses_to_clean = [analysis]
    else:
        analyses_to_clean = worx.analyses

    print("Cleaning up....")
    for ana in analyses_to_clean:
        ana.fetch()

        for fig in ana.figures:
            fig.fetch()
            for rev in fig.revisions:
                rev.delete(delete=True)

            fig.delete(delete=True)

    if clean_assets:
        for asset in worx.assets:
            asset.delete(delete=True)

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

    gf = get_gf()
    worx = gf.find_workspace(FindByName("Integration tests", create=True))
    ana = worx.get_analysis(config["name"])

    clean_up(analysis=ana)

    notebook = config.get('notebook', 'integration_tests.ipynb')
    results_file = config.get('results_file', 'integration_test.json')

    print(f"Running configuration {idx + 1}/{len(all_configurations)}: ")
    print(f'  * Name: {config["name"]}')
    print(f"  * Python: {config['python']}")
    print(f"  * Notebook: {notebook}")
    print(f"  * Result file: {results_file}")
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

    with open(os.path.join(out_dir, ".gofigr"), 'w') as f:
        json.dump({
            "username": os.environ["GF_TEST_USER"],
            "password": os.environ["GF_TEST_PASSWORD"],
            "workspace": worx.api_id,
            "analysis": ana.api_id,
            "url": "https://api-dev.gofigr.io",
            "auto_publish": True
        }, f)

    runner_args = ["bash", run_one, out_dir, os.path.join(out_dir, "driver.log"),
                   config["python"], config["service"],
                   config["dependencies"],
                   notebook, results_file]
    if not args.no_headless:
        runner_args.append("--headless")

    print(f"  => Running {format_cmd(runner_args)}")
    cp = subprocess.run(runner_args, check=False)
    print(f"Exit code: {cp.returncode}")
    if cp.returncode != 0:
        print(f"  => Process failed with code {cp.returncode}")

        with open(os.path.join(out_dir, "errors.json"), 'w') as ef:
            json.dump({"error": None if cp.stderr is None else cp.stderr.decode('ascii', errors='ignore')}, ef)

        return {'success': False, 'analysis': ana, 'log_path': os.path.join(out_dir, "driver.log")}
    else:
        print("  => Complete")
        return {'success': True, 'analysis': ana}




def test_wrapper(messages, config, args, idx, all_configurations):
    test_name = config["name"].replace(".", "_")

    start_time = datetime.datetime.now()
    analysis = None
    try:
        messages.testStarted(test_name, flowId=test_name)
        res = run_one_config(args, idx, config, all_configurations, messages)

        analysis = res['analysis']
        if not res['success']:
            with open(res['log_path'], 'r') as f:
                messages.testFailed(test_name, flowId=test_name, message="Test failed", details=f.read())
        else:
            messages.testFinished(test_name, testDuration=datetime.datetime.now() - start_time,
                                  flowId=test_name)
    except Exception as e:  # pylint: disable=broad-exception-caught
        messages.testFailed(test_name, message=str(e), flowId=test_name)
    finally:
        if analysis is not None and not args.no_cleanup:
            clean_up(analysis=analysis)


def main():
    parser = ArgumentParser(description="Runs integration tests based on a config file")
    parser.add_argument("config", help="config file (JSON)")
    parser.add_argument("output", help="output directory")
    parser.add_argument("--no-headless", action="store_true", help="Whether to NOT run in headless mode. Default is true.")
    parser.add_argument("--force", action="store_true", help="Force re-run even if directory already exists")
    parser.add_argument("--threads", action="store", type=int, help="Number of threads to use", default=10)
    parser.add_argument("--subset", action="store", nargs="+", help="Specify names of configurations to run")
    parser.add_argument("--no-cleanup", action="store_true", help="Do not clean up after running")
    args = parser.parse_args()

    with open(args.config, "r") as f:
        all_configurations = json.load(f)

        if isinstance(all_configurations, dict):
            all_configurations = [all_configurations]

    if args.subset and len(args.subset) > 0:
        all_configurations = [conf for conf in all_configurations if conf["name"] in args.subset]

    messages = TeamcityServiceMessages()
    messages.testSuiteStarted("Compatibility checks")
    messages.testCount(len(all_configurations))

    clean_up(clean_assets=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
        for idx, config in enumerate(all_configurations):
            executor.submit(test_wrapper, messages, config, args, idx, all_configurations)

    if not args.no_cleanup:
        clean_up(analysis=None, clean_assets=True)

    messages.testSuiteFinished("Compatibility checks")

if __name__ == "__main__":
    main()
