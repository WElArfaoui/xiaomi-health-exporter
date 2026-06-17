"""Per-account export: request the data copy and later download + decrypt + extract it.

Output layout:  <output_dir>/<label>/<label>_<DDMMYYYY>/   (extracted CSVs)
                <output_dir>/<label>/<label>_<DDMMYYYY>.zip (the encrypted ZIP, kept)
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import config, xiaomi
from .mailbox import Imap
from .otp import ManualOtp, ImapOtp


@dataclass
class Account:
    email: str
    password: str                 # Xiaomi account password
    imap_password: str = ""       # mailbox password (often same as Xiaomi password)
    label: str = ""               # folder name; defaults to the e-mail local part

    def __post_init__(self):
        if not self.label:
            self.label = self.email.split("@")[0]
        if not self.imap_password:
            self.imap_password = self.password


def _otp_source(acc: Account, settings: config.Settings):
    if settings.otp_mode == "imap":
        if not settings.imap_host:
            raise RuntimeError("otp_mode='imap' requires --imap-host")
        imap = Imap(settings.imap_host, settings.imap_port, acc.email, acc.imap_password)
        return ImapOtp(imap)
    return ManualOtp(acc.label)


def _context(p, acc: Account, settings: config.Settings):
    sess = settings.sessions_dir / acc.label
    sess.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        user_data_dir=str(sess), headless=settings.headless, accept_downloads=True,
        locale="en-US", viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"])


def _state_file(acc: Account, settings: config.Settings) -> Path:
    d = settings.sessions_dir / acc.label
    d.mkdir(parents=True, exist_ok=True)
    return d / "pending.json"


def request(acc: Account, settings: config.Settings, log=print) -> None:
    """Log in and submit the MI Fitness data-copy request."""
    otp = _otp_source(acc, settings)
    baseline = {}
    with sync_playwright() as p:
        ctx = _context(p, acc, settings)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(config.ACCOUNT_HOME_URL, wait_until="networkidle", timeout=40000)
        if not xiaomi.is_logged_in(page):
            log(f"[{acc.label}] logging in ...")
            xiaomi.login(page, acc.email, acc.password, otp, log,
                         abort_on_captcha=settings.headless)
        # baseline of the inbox so collect() (imap mode) can spot the new download e-mail
        if settings.otp_mode == "imap":
            baseline = Imap(settings.imap_host, settings.imap_port,
                            acc.email, acc.imap_password).snapshot_uids()
        log(f"[{acc.label}] requesting data copy ...")
        xiaomi.request_export(page, acc.email, acc.password, otp, log)
        ctx.close()
    _state_file(acc, settings).write_text(json.dumps(
        {"email": acc.email, "label": acc.label, "baseline": baseline,
         "requested_at": datetime.now().isoformat()}))
    log(f"[{acc.label}] request submitted. The download e-mail can take minutes to ~15 working days.")


def _extract(zip_path: Path, dest: Path, password: str | None, log=print) -> str:
    dest.mkdir(parents=True, exist_ok=True)
    pwd = password.encode() if password else None
    try:
        import pyzipper
        with pyzipper.AESZipFile(str(zip_path)) as zf:
            zf.extractall(path=str(dest), pwd=pwd)
        return "pyzipper(AES)"
    except Exception as e:
        log(f"  pyzipper failed ({e}); trying standard zipfile")
        import zipfile
        with zipfile.ZipFile(str(zip_path)) as zf:
            zf.extractall(path=str(dest), pwd=pwd)
        return "zipfile"


def collect(acc: Account, settings: config.Settings, log=print,
            url: str | None = None, zip_password: str | None = None) -> Path | None:
    """Download + decrypt + extract. In manual mode pass url+zip_password (from the e-mail);
    in imap mode they are read automatically. Returns the extracted folder, or None."""
    if url is None:
        if settings.otp_mode != "imap":
            raise RuntimeError("manual mode: pass the download URL and ZIP password from the e-mail")
        state_f = _state_file(acc, settings)
        baseline = json.loads(state_f.read_text())["baseline"] if state_f.exists() else {}
        info = Imap(settings.imap_host, settings.imap_port,
                    acc.email, acc.imap_password).find_download(baseline)
        if not info:
            log(f"[{acc.label}] download e-mail not arrived yet")
            return None
        url, zip_password = info["url"], info["password"]

    otp = _otp_source(acc, settings)
    stamp = datetime.now().strftime("%d%m%Y")
    name = f"{acc.label}_{stamp}"
    base = settings.output_dir / acc.label
    zip_path = base / f"{name}.zip"
    dest = base / name

    with sync_playwright() as p:
        ctx = _context(p, acc, settings)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        log(f"[{acc.label}] downloading ...")
        zips = xiaomi.download_files(page, url, zip_path, acc.email, acc.password, otp, log)
        ctx.close()
    for z in zips:
        engine = _extract(z, dest, zip_password, log)
    n = len(list(dest.glob("*")))
    log(f"[{acc.label}] extracted ({engine}) -> {dest} ({n} files)")
    sf = _state_file(acc, settings)
    if sf.exists():
        sf.unlink()
    return dest
