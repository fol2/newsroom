#!/usr/bin/env python3
import argparse,json
from pathlib import Path
from newsroom.increment10.decision import decide

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--inventory",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args();report=decide(json.loads(a.inventory.read_bytes()));a.output.write_bytes(report.canonical_bytes());print(json.dumps({"status":"COMPLETE","disposition":report.disposition.value,"decision_digest":report.digest,"increment11_eligible":report.increment11_eligible},sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
