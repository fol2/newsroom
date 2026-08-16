#!/usr/bin/env python3
"""Create a local-only Increment 10 readiness receipt; never starts execution."""
import argparse,json
from pathlib import Path
from newsroom.increment10.deployment import assert_current,prove_readiness

def main()->int:
 p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,required=True); p.add_argument("--production-digest",required=True); p.add_argument("--public-surface-digest",required=True); args=p.parse_args()
 receipt=prove_readiness(args.root.resolve(),production_digest=args.production_digest,public_surface_digest=args.public_surface_digest); assert_current(receipt)
 print(json.dumps({"status":"READY_NO_EXECUTION","receipt_digest":receipt.digest,"receipt":json.loads(receipt.canonical_bytes())},sort_keys=True)); return 0
if __name__=="__main__":raise SystemExit(main())
