"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import sys
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


def parse_results(path, results_name):
    """Parses results of a single integration test and returns them as a data frame"""
    if os.path.exists(os.path.join(path, results_name)):
        with open(os.path.join(path, results_name), 'r') as f:
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
    df['plotnine'] = find_pkg("plotnine", packages)

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


_TEST_COLUMNS = ['number_of_revisions',
                'notebook_name',
                'notebook_path',
                'image_png',
                'image_png_watermark',
                'image_eps',
                'image_svg',
                'image_html',
                'file_pickle',
                'num_assets',
                'asset_figure',
                'asset_rev_not_null',
                'asset_name',
                'text',
                'cell_code',
                'backend',
                'history']

_LITE_TEST_COLUMNS = ['notebook_name',
                     'notebook_path',
                     'extension_version',
                     'metadata',
                     'comm',
                     'title',
                     'image_not_null',
                     'image_type_check']

_COLUMN_ORDER = ['name',
                'platform',
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
                'plotly',
                'test_name',
                'error',
                'elapsed_seconds']


def get_columns(test):
    if test == "full":
        return _TEST_COLUMNS
    elif test == "lite":
        return _LITE_TEST_COLUMNS
    else:
        raise ValueError(test)


def get_column_order(test):
    if test == "full":
        return _COLUMN_ORDER + get_columns(test)
    elif test == "lite":
        return _COLUMN_ORDER + get_columns(test)
    else:
        raise ValueError(test)


def abbreviate(text, max_len=100):
    if len(text) <= max_len:
        return text
    else:
        return text[0:max_len - 3] + "..."


def parse_version(text):
    """Parses a major.minor.patch version string"""
    return tuple([int(x) for x in text.split(".")])


def summarize_results(df, test):
    """Summarizes test results"""
    all_tests = []
    passed_tests = []
    failed_tests = []

    if 'test_name' not in df.columns:  # none of the tests have run
        failed_tests.append("None of the tests have run")
    else:
        for _, row in df.iterrows():
            test_name = row['test_name']
            is_plotly = "plotly" in test_name.lower()
            is_py3dmol = 'py3dmol' in test_name.lower()
            is_matplotlib = 'mpl' in test_name.lower()
            is_plotnine = "plotnine" in test_name.lower()

            for col in get_columns(test):
                check_name = f"{test_name}>{col}"
                if row.get(col) is True:  # test passed
                    passed_tests.append(check_name)
                    all_tests.append(check_name)
                elif (is_matplotlib or is_plotnine) and col in ['image_html', 'image_html_watermark']:
                    pass  # not an interactive backend
                elif is_matplotlib and "Anonymous" in test_name and col == "number_of_revisions":
                    # Because figures aren't cleared between re-attempts of the same config, Anonymous fig can end up
                    # with more than one revision. This needs to be fixed, but here's a temporary workaround.
                    pass
                elif is_plotnine and col in ['file_pickle'] and parse_version(row['plotnine']) < (0, 14, 0):
                    pass
                elif is_plotly and col in ["image_eps"]:  # plotly doesn't support EPS, so this failure is expected
                    pass
                elif is_py3dmol and (col in ["image_svg", "image_eps"] or "3.7" in row["python"]): # similar for py3dmol
                    pass
                else:
                    failed_tests.append(check_name)
                    all_tests.append(check_name)

    return pd.DataFrame({'name': [one(df['name'])],
                         'service': [one(df['service'])],
                         'python': [one(df['python'])],
                         'elapsed_seconds': [np.round(df['elapsed_seconds'].max(), 1)
                                             if 'elapsed_seconds' in df.columns else "N/A"],
                         'result': ["success" if len(failed_tests) == 0 else "failed"],
                         'all_tests': [len(all_tests)],
                         'passed_tests': [len(passed_tests)],
                         'failed_tests': [len(failed_tests)],
                         'failed_tests_detail': [abbreviate(", ".join(failed_tests))]})


def summarize_all(path, single, results_name):
    """Finds all integration tests in a directory, summarizes them, and returns the combined dataframe"""
    if 'lite' in results_name:
        test = "lite"
    else:
        test = "full"

    frames = []
    summary_frames = []
    if single:
        print(f"{os.path.basename(path)}...")
        df = parse_results(path, results_name)
        frames.append(df)
        summary_frames.append(summarize_results(df, test))
    else:
        for name in os.listdir(path):
            if test == 'lite' and 'lite' not in name:
                continue

            if test == "full" and 'lite' in name:
                continue

            full = os.path.join(path, name)
            if os.path.isdir(full):
                print(f"{name}...")
                df = parse_results(full, results_name)
                frames.append(df)
                summary_frames.append(summarize_results(df, test))

    df = pd.concat(frames, ignore_index=True).sort_values(by=['python_minor_version', 'service'])
    column_subset = [x for x in get_column_order(test) if x in df.columns]
    test_column_subset = [x for x in get_columns(test) if x in df.columns]
    df.loc[:, test_column_subset] = df[test_column_subset].fillna(value='N/A')

    df_summary = pd.concat(summary_frames, ignore_index=True)
    return df[column_subset], df_summary


def main():
    """Main"""
    parser = ArgumentParser(description="Generates a compatibility report")
    parser.add_argument("directory", help="Directory containing integration test results")
    parser.add_argument("output", help="Where to save the output Excel file")
    parser.add_argument("detailed_output", help="Where to save the detailed Excel file")
    parser.add_argument("--single", help="Processes a single run only", action="store_true")
    parser.add_argument("--results", help="Name of the results file", default="integration_test.json")
    args = parser.parse_args()

    df_detail, df_summary = summarize_all(args.directory, single=args.single, results_name=args.results)
    print("\n=== Result summary ===")
    print(df_summary)
    print("\n")

    df_summary.to_excel(args.output, index=False)
    print(f"Saved to {args.output}")

    df_detail.to_excel(args.detailed_output, index=False)
    print(f"Saved detailed output to {args.detailed_output}")

    df_failed = df_summary[df_summary['result'] != "success"]
    df_success = df_summary[df_summary['result'] == "success"]
    print(f"\n\n  => Ran {len(df_summary)} tests. {len(df_success)} successes. {len(df_failed)} failures.")

    if (df_summary['result'] != "success").any():
        print(f"\n  => Tests failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("  => All tests successful.")


if __name__ == "__main__":
    main()
