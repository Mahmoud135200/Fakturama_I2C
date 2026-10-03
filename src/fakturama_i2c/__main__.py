
from __future__ import annotations
import argparse
import json
import sys
import time

from .extract import ExtractionError, UnsupportedDocumentError, extract


def main(argv=None) -> int:
   
    ap = argparse.ArgumentParser(
        prog="fakturama_i2c",
        description="Order image -> saved, verified Order + linked Invoice in Fakturama.")
    
    sub = ap.add_subparsers(dest="cmd", required=True)

    rn = sub.add_parser("run", help="process an order document end to end")
    rn.add_argument("image", metavar="DOCUMENT",
                    help="order image (PNG/JPG/...) or PDF to process")
    rn.add_argument("--out-dir", default=None,
                    help="where to write report.json + screenshots "
                         "(default: runs/<timestamp>)")
    rn.add_argument("--no-seed-payments", dest="seed_payments", action="store_false",
                    help="skip the up-front terms-of-payment seeding and let task 2.10 "
                         "create the extracted payment method on demand instead")
    rn.set_defaults(seed_payments=True)

    a = ap.parse_args(argv)

   
    try:
        order = extract(a.image)
    except (ExtractionError, UnsupportedDocumentError) as e:
        print(e, file=sys.stderr)
        return 2

  
    from .ui.app import App
    from .ui.flow import run as run_flow

    
    out_dir = a.out_dir or f"runs/{time.strftime('%Y%m%d-%H%M%S')}"
    print("attaching to Fakturama...")
    app = App.attach()
    print(f"running flow, writing evidence to {out_dir}")

    report = run_flow(order, app, out_dir, seed_payments=a.seed_payments)
    print(json.dumps(report.to_dict(), indent=2))
    
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
