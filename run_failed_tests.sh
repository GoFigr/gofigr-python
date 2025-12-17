#!/usr/bin/env bash
#
# Run only the failed tests from the test suite
#
# Usage:
#   ./run_failed_tests.sh

cd "$(dirname "$0")/.."

python -m unittest -v --failfast \
    tests.test_client.TestAssets.test_asset_creation \
    tests.test_client.TestFigures.test_revisions \
    tests.test_client.TestSizeCalculation.test_size \
    tests.test_client.TestAssets.test_find_hash \
    tests.test_client.TestFigures.test_timestamp_propagation \
    tests.test_client.TestPermissions.test_exclusivity \
    tests.test_client.TestSharing.test_malicious_sharing \
    tests.test_client.TestSharing.test_sharing
