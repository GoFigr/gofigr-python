"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import json
import os
import shutil
import subprocess
import sys
from argparse import ArgumentParser

from tqdm import tqdm

from gofigr import GoFigr
from gofigr.jupyter import from_config_or_env


@from_config_or_env("GF_", os.path.join(os.environ['HOME'], '.gofigr'))
def get_gf(username, password):
    return GoFigr(username=username, password=password, url="https://api-dev.gofigr.io")


def clean_up():
    gf = get_gf()

    ana = gf.primary_workspace.get_analysis("Integration tests", create=True)
    print("Cleaning up....")
    for fig in tqdm(ana.figures):
        for rev in fig.revisions:
            rev.delete(delete=True)

        fig.delete(delete=True)


def main():
    parser = ArgumentParser(description="Runs integration tests based on a config file")
    parser.add_argument("config", help="config file (JSON)")
    parser.add_argument("output", help="output directory")
    parser.add_argument("--force", action="store_true", help="Force re-run even if directory already exists")
    args = parser.parse_args()

    run_one = os.path.join(os.path.dirname(sys.argv[0]), "run_one.sh")
    clean_up()

    with open(args.config, "r") as f:
        all_configurations = json.load(f)

    for idx, config in enumerate(tqdm(all_configurations)):
        out_dir = os.path.join(args.output, config["name"])

        print(f"Running configuration {idx + 1}/{len(all_configurations)}: ")
        print(f"  * Python: {config['python']}")
        print(f"  * Dependencies: {config['dependencies']}")
        print(f"  * Directory: {out_dir}")

        if os.path.exists(out_dir):
            if args.force:
                shutil.rmtree(out_dir)
            else:
                print("  => Path exists. Skipping\n")
                continue

        os.makedirs(out_dir, exist_ok=True)

        with open(os.path.join(out_dir, "config.json"), 'w') as f:
            json.dump(config, f)

        with open(os.path.join(out_dir, "output.txt"), 'wb') as f:
            cp = subprocess.run(["bash", run_one, out_dir, config["python"], config["service"], config["dependencies"]],
                                stdout=f, stderr=f)
            if cp.returncode != 0:
                print(f"Process failed with code {cp.returncode}")

                with open(os.path.join(out_dir, "errors.json"), 'w') as ef:
                    json.dump({"error": None if cp.stderr is None else cp.stderr.decode('ascii', errors='ignore')}, ef)

        print("  => Complete")

    clean_up()
    print("All done")


if __name__ == "__main__":
    main()
