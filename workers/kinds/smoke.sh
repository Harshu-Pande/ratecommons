#!/usr/bin/env bash
# Kind "smoke": checks a helper's fork end to end without touching any data. Prints its inputs, installs the
# package, and reports which payer hosts this runner reaches (runner regions vary).
set -euo pipefail
echo "worker=$RC_WORKER id=$RC_ID part=$RC_PART/$RC_PARTS request=${RC_REQUEST:-}"
pip install -q -e . && python -c "import ticdata; print('ticdata imports')"
for h in transparency-in-coverage.uhc.com health1.aetna.com d25kgz5rikkq4n.cloudfront.net www.bcbstx.com \
         www.anthem.com www.molinahealthcare.com huggingface.co; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://$h/" || echo "fail")
  echo "reach $h: $code"
done
{ echo "### smoke $RC_ID part $RC_PART of $RC_PARTS"; echo "request: ${RC_REQUEST:-}"; } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
