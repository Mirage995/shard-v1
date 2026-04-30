#!/usr/bin/env bash
# d2_run_all.sh -- Run D2 frustration benchmark to completion.
#
# The benchmark exits after each ARM (ARM_A then ARM_B) so that ChromaDB
# file handles are released and the next run can do a clean snapshot
# restore. This wrapper invokes python the necessary number of times in
# sequence: PAIRED_SESSIONS * 2 invocations total (default 6).
#
# Usage:
#     bash backend/d2_run_all.sh
set -e
cd "$(dirname "$0")/.."

PAIRS=3
INVOCATIONS=$((PAIRS * 2))

echo "==============================================================="
echo "D2 wrapper: $INVOCATIONS sequential python invocations expected"
echo "==============================================================="

for i in $(seq 1 $INVOCATIONS); do
    echo
    echo "------- D2 invocation $i / $INVOCATIONS -------"
    python backend/d2_frustration_benchmark.py
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "[D2 wrapper] python exited with code $rc, aborting"
        exit $rc
    fi
done

echo
echo "==============================================================="
echo "D2 wrapper: all invocations complete"
echo "==============================================================="
