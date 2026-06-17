"""Command-line interface for the Xiaomi Mi Fitness health-data exporter.

Examples
--------
  # ONE account, type the codes yourself (no e-mail credentials needed):
  python -m xiaomi_export request  --email you@example.com
  # ...wait for the e-mail, then:
  python -m xiaomi_export download --email you@example.com \
         --url "<link from the e-mail>" --password "<zip password from the e-mail>"

  # MANY accounts, codes read automatically over IMAP:
  python -m xiaomi_export request  --accounts accounts.csv --otp imap --imap-host mail.example.com
  python -m xiaomi_export download --accounts accounts.csv --otp imap --imap-host mail.example.com
"""
from __future__ import annotations
import argparse
import getpass
import sys
import time

from . import config, exporter, accounts as accounts_mod
from .exporter import Account


def _settings(args) -> config.Settings:
    s = config.Settings(
        output_dir=args.output_dir,
        sessions_dir=args.sessions_dir,
        headless=args.headless,
        otp_mode=args.otp,
        imap_host=args.imap_host or "",
        imap_port=args.imap_port,
    )
    s.ensure_dirs()
    return s


def _accounts(args) -> list[Account]:
    if args.accounts:
        return accounts_mod.load_csv(args.accounts)
    if args.email:
        pw = args.password or getpass.getpass(f"Xiaomi password for {args.email}: ")
        return [Account(email=args.email, password=pw, label=args.label or "")]
    sys.exit("Provide --email (single account) or --accounts file.csv (many).")


def cmd_request(args) -> None:
    settings = _settings(args)
    accs = _accounts(args)
    for acc in accs:
        if args.skip_done and (settings.sessions_dir / acc.label / "pending.json").exists():
            print(f"[{acc.label}] already requested, skipping")
            continue
        try:
            exporter.request(acc, settings)
        except Exception as e:
            print(f"[{acc.label}] ERROR: {e}")
        if len(accs) > 1:
            time.sleep(args.gap)


def cmd_download(args) -> None:
    settings = _settings(args)
    accs = _accounts(args)
    for acc in accs:
        try:
            exporter.collect(acc, settings, url=args.url, zip_password=args.password_zip)
        except Exception as e:
            print(f"[{acc.label}] ERROR: {e}")
        if len(accs) > 1:
            time.sleep(args.gap)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="xiaomi-export",
                                description="Export Xiaomi Mi Fitness health data (GDPR copy).")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--email", help="single account e-mail")
        sp.add_argument("--password", help="Xiaomi password (omit to be prompted)")
        sp.add_argument("--label", help="folder name for this account")
        sp.add_argument("--accounts", help="CSV with many accounts")
        sp.add_argument("--output-dir", default="./xiaomi_data")
        sp.add_argument("--sessions-dir", default="./.sessions")
        sp.add_argument("--otp", choices=["manual", "imap"], default="manual",
                        help="how to obtain the e-mail verification codes")
        sp.add_argument("--imap-host", help="IMAP server (for --otp imap)")
        sp.add_argument("--imap-port", type=int, default=993)
        sp.add_argument("--gap", type=int, default=30, help="seconds between accounts (bulk)")
        grp = sp.add_mutually_exclusive_group()
        grp.add_argument("--headful", dest="headless", action="store_false", default=False,
                         help="show the browser window (default; needed to solve captchas)")
        grp.add_argument("--headless", dest="headless", action="store_true",
                         help="no window (only works if the account never shows a captcha)")

    pr = sub.add_parser("request", help="request the data copy")
    common(pr)
    pr.add_argument("--skip-done", action="store_true", help="skip accounts already requested")
    pr.set_defaults(func=cmd_request)

    pd = sub.add_parser("download", help="download + decrypt + extract when the e-mail arrived")
    common(pd)
    pd.add_argument("--url", help="download link from the e-mail (manual mode)")
    pd.add_argument("--password-zip", help="ZIP password from the e-mail (manual mode)")
    pd.set_defaults(func=cmd_download)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
