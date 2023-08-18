"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
from argparse import ArgumentParser

import numpy as np
import pandas as pd
import json
import os
import re


def find_pkg(name, lines):
    """Given output of pip freeze, finds the exact package version"""
    m = [x for x in lines if x.startswith(f"{name}==")]
    if len(m) == 0:
        return None
    elif len(m) == 1:
        return re.match(r'.*==(.*)', m[0]).group(1)
    else:
        raise ValueError(f'Ambiguous: {name}. Matches: {m}')


def parse_results(path):
    """Parses results of a single integration test and returns them as a data frame"""
    if os.path.exists(os.path.join(path, 'integration_test.json')):
        with open(os.path.join(path, 'integration_test.json'), 'r') as f:
            results = json.load(f)
    else:
        results = {'platform': 'N/A',
                   'results': [{'name': 'N/A'}]}

    platform = results['platform']
    tests = results['results']

    df = pd.DataFrame(tests)
    df['platform'] = platform

    if os.path.exists(os.path.join(path, 'pip_freeze.txt')):
        with open(os.path.join(path, 'pip_freeze.txt'), 'r') as f:
            packages = [x.strip() for x in f.readlines()]
    else:
        packages = []

    df['notebook'] = find_pkg("notebook", packages)
    df['jupyterlab'] = find_pkg("jupyterlab", packages)
    df['jupyter_server'] = find_pkg("jupyter_server", packages)
    df['jupyter_core'] = find_pkg("jupyter_core", packages)
    df['jupyter_client'] = find_pkg("jupyter_client", packages)
    df['ipython'] = find_pkg("ipython", packages)
    df['ipykernel'] = find_pkg("ipykernel", packages)
    df['matplotlib'] = find_pkg("matplotlib", packages)
    df['plotly'] = find_pkg("plotly", packages)

    with open(os.path.join(path, "config.json"), 'r') as f:
        config = json.load(f)

    if os.path.exists(os.path.join(path, "python_version.txt")):
        with open(os.path.join(path, "python_version.txt"), 'r') as f:
            txt = f.read()
            df['python'] = re.match(r'Python\s+([\d\.]+)', txt).group(1)
            df['python_minor_version'] = int(re.match(r'Python\s+3\.(\d+)\..*', txt).group(1))
    else:
        df['python'] = 'N/A'
        df['python_minor_version'] = 'N/A'

    df['service'] = config['service']
    df['name'] = config['name']

    return df


def one(xs):
    """Makes sure there's exactly one unique value in a list and returns it"""
    xs = list(set(xs))
    if len(xs) == 0:
        return None
    elif len(xs) == 1:
        return xs[0]
    else:
        raise ValueError(xs)


def summarize_results(df):
    """Summarizes test results"""
    collapsed_results = {}
    for col in df.columns:
        if df[col].dtype == bool:

            failing = df[~df[col]]
            passing = df[df[col]]
            if len(failing) == 0:
                collapsed_results[col] = "✓"
            else:
                collapsed_results[col] = f"{len(passing)}/{len(df)} passed\n✗: " + \
                                         ", ".join(failing['test_name']) + \
                                         "\n" + "✓: " + ", ".join(passing['test_name'])
        elif col == "error":
            collapsed_results[col] = ", ".join([str(x) for x in df[col] if x is not None])
        elif col != 'test_name':
            collapsed_results[col] = ", ".join([str(x) for x in df[col].unique()])

    return collapsed_results


TEST_COLUMNS = ['number_of_revisions',
                'notebook_name',
                'notebook_path',
                'image_png',
                'image_png_watermark',
                'image_eps',
                'image_svg',
                'image_html',
                'text',
                'cell_code',
                'cell_id']

COLUMN_ORDER = ['platform',
                'name',
                'service',
                'error',
                'python',
                'python_minor_version',

                'notebook',
                'jupyterlab',
                'jupyter_server',
                'jupyter_core',
                'jupyter_client',
                'ipython',
                'ipykernel',
                'matplotlib',
                'plotly'] + TEST_COLUMNS


def summarize_all(path):
    """Finds all integration tests in a directory, summarizes them, and returns the combined dataframe"""
    summaries = []
    for name in os.listdir(path):
        full = os.path.join(path, name)
        if os.path.isdir(full):
            print(f"{name}...")
            summary = summarize_results(parse_results(full))
            summaries.append(summary)

    df = pd.DataFrame(summaries).sort_values(by=['python_minor_version', 'service'])[COLUMN_ORDER]
    df.loc[:, TEST_COLUMNS] = df[TEST_COLUMNS].fillna(value='E')
    return df


def main():
    """Main"""
    parser = ArgumentParser(description="Generates a compatibility report")
    parser.add_argument("directory", help="Directory containing integration test results")
    parser.add_argument("output", help="Where to save the output Excel file")
    args = parser.parse_args()

    df = summarize_all(args.directory)
    print(df)
    df.to_excel(args.output, index=False)
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
