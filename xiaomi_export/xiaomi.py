"""Xiaomi privacy-portal automation (Playwright).

Implements the real "Download a copy" (GDPR export) flow for the MI Fitness product:
login -> e-mail verification (OTP) -> Privacy -> Manage your data -> MI Fitness ->
"Download a copy" -> confirm; and later the download page (SSO login -> click "File #N").

The verification code is provided by an OTP source (manual typing or IMAP). The slide
captcha that Xiaomi shows on new logins must be solved by a human (run with a visible window).
"""
from __future__ import annotations
import re
import time
from pathlib import Path

from . import config


class CaptchaRequired(RuntimeError):
    """A captcha appeared but the run is headless (cannot be solved automatically)."""


# ----------------------------------------------------------------- small helpers
def _accept_cookies(page) -> None:
    try:
        page.get_by_role("button", name=re.compile("Accept cookies", re.I)).click(timeout=3000)
    except Exception:
        pass


def _check_agreement(page) -> None:
    try:
        cb = page.query_selector("input.ant-checkbox-input")
        if cb and cb.is_visible() and not cb.is_checked():
            cb.check()
    except Exception:
        pass


def _click_agree(page) -> bool:
    try:
        agree = page.get_by_role("button", name=re.compile(r"^\s*Agree\s*$", re.I))
        if agree.count() and agree.first.is_visible():
            agree.first.click()
            return True
    except Exception:
        pass
    return False


def _otp_inputs(page):
    cand = []
    for inp in page.query_selector_all("input"):
        try:
            if not inp.is_visible():
                continue
            name = (inp.get_attribute("name") or "").lower()
            typ = (inp.get_attribute("type") or "text").lower()
            if name in ("account", "password") or typ in ("checkbox", "password"):
                continue
            if typ in ("text", "tel", "number"):
                cand.append(inp)
        except Exception:
            continue
    return cand


def _fill_otp(page, code: str) -> None:
    cand = _otp_inputs(page)
    if len(cand) == 1:
        cand[0].click(); cand[0].fill(code)
    elif len(cand) >= len(code):
        for ch, inp in zip(code, cand):
            inp.click(); inp.fill(ch)
    elif cand:
        cand[0].click(); page.keyboard.type(code)
    else:
        page.keyboard.type(code)
    try:
        page.get_by_role("button",
            name=re.compile(r"Verify|Confirm|Submit|^OK$|Done|Sign in|Next", re.I)).last.click(timeout=3000)
    except Exception:
        try:
            page.keyboard.press("Enter")
        except Exception:
            pass


def _captcha_visible(page) -> bool:
    mv = page.query_selector(".miverify_cancel_btn, .miverify_refresh_btn, [class*=miverify]")
    return bool(mv and mv.is_visible())


def _has_login_form(page) -> bool:
    el = page.query_selector('input[name="account"]')
    return bool(el and el.is_visible())


def _on_auth_screen(page) -> bool:
    try:
        return page.get_by_text("Account Authentication", exact=False).count() > 0
    except Exception:
        return False


def _rate_limited(page) -> bool:
    try:
        return page.get_by_text("Too many frequent attempts", exact=False).count() > 0
    except Exception:
        return False


def is_logged_in(page) -> bool:
    url = page.url
    bad = ["/fe/service/login", "/service/login", "account/error", "identity/verif",
           "verifyEmail", "/sns/login", "facebook.com", "/identity/"]
    if any(b in url for b in bad):
        return False
    return "account.xiaomi.com" in url


def _fill_login_form(page, email: str, password: str) -> None:
    _check_agreement(page)
    page.fill('input[name="account"]', email)
    page.fill('input[name="password"]', password)
    page.get_by_role("button", name=re.compile(r"^\s*Sign in\s*$", re.I)).last.click()
    time.sleep(4)


# ----------------------------------------------------------------- login
def login(page, email: str, password: str, otp, log=print,
          abort_on_captcha: bool = False, timeout: int = config.LOGIN_TIMEOUT) -> bool:
    """Full login. `otp` is an OTP source with .prime()/.get(). Returns True if authenticated."""
    page.goto(config.LOGIN_URL, wait_until="networkidle", timeout=45000)
    _accept_cookies(page)
    _check_agreement(page)
    page.fill('input[name="account"]', email)
    page.fill('input[name="password"]', password)
    page.get_by_role("button", name=re.compile(r"^\s*Sign in\s*$", re.I)).last.click()

    sent = False
    otp_filled = False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _click_agree(page):
            time.sleep(1); continue
        if is_logged_in(page):
            return True
        if _captcha_visible(page):
            if abort_on_captcha:
                raise CaptchaRequired("captcha on login (needs a visible window to solve)")
            log("  >>> Solve the captcha in the browser window <<<")
            time.sleep(2); continue
        if not sent:
            send = page.get_by_role("button", name=re.compile(r"^\s*Send\s*$", re.I))
            try:
                if send.count() and send.first.is_visible():
                    otp.prime()
                    send.first.click()
                    sent = True
                    time.sleep(2); continue
            except Exception:
                pass
        if sent and not otp_filled and _otp_inputs(page):
            try:
                _fill_otp(page, otp.get(config.OTP_WAIT_TIMEOUT))
                otp_filled = True
                time.sleep(2); continue
            except Exception as e:
                log(f"  OTP error: {e}")
        time.sleep(3)
    return is_logged_in(page)


# ----------------------------------------------------------------- generic auth resolver
def resolve_auth(page, email: str, password: str, otp, log=print, timeout: int = 220) -> bool:
    """Resolve any challenge that pops up (login form / Agree modal / step-up Send+OTP).
    On captcha it waits for a human (visible window). Aborts on Xiaomi rate-limit."""
    sent = False
    login_done = False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _click_agree(page):
            time.sleep(1); continue
        if _rate_limited(page):
            raise RuntimeError("Xiaomi rate-limit ('Too many frequent attempts'). Try again later.")
        if _has_login_form(page):
            if _captcha_visible(page):
                log("  >>> Solve the captcha in the browser window <<<")
                time.sleep(2); continue
            if not login_done:
                _fill_login_form(page, email, password)
                login_done = True; sent = False
                continue
            time.sleep(2); continue
        if _on_auth_screen(page):
            send = page.get_by_role("button", name=re.compile(r"^\s*Send\s*$", re.I))
            if (send.count() and send.first.is_visible()) and not sent:
                otp.prime()
                send.first.click(); sent = True
                time.sleep(3); continue
            if sent and _otp_inputs(page):
                _fill_otp(page, otp.get(config.OTP_WAIT_TIMEOUT))
                time.sleep(4); continue
            time.sleep(2); continue
        return True
    return not _on_auth_screen(page)


# ----------------------------------------------------------------- request export
def _click_product_download(page, product: str) -> str:
    """Click the 'Download a copy' button of the given product row (never 'Delete')."""
    return page.evaluate("""(product) => {
        const labels=[...document.querySelectorAll('*')].filter(
            e=>e.children.length===0 && (e.innerText||'').trim()===product);
        if(!labels.length) return 'no-label';
        let row=labels[0];
        for(let i=0;i<6 && row.parentElement;i++){
            row=row.parentElement;
            if(row.querySelectorAll('button').length>=2) break;
        }
        const btns=[...row.querySelectorAll('button')];
        let dl=btns.find(b=>(b.getAttribute('title')||'').trim()==='Download a copy');
        if(!dl && btns.length>=2) dl=btns[0];
        if(!dl) return 'no-button';
        if((dl.getAttribute('title')||'').trim()==='Delete') return 'safety-abort';
        dl.click(); return 'clicked';
    }""", product)


def _confirm_download_modal(page, log=print, timeout: int = 130) -> bool:
    """Confirm the 'Download a copy' modal: wait for the 'OK (Ns)' countdown then click OK."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for b in page.query_selector_all("button"):
            try:
                t = (b.inner_text() or "").strip()
                if re.match(r"^OK", t, re.I) and "(" not in t and not b.is_disabled():
                    b.click()
                    return True
            except Exception:
                continue
        time.sleep(2)
    return False


def request_export(page, email: str, password: str, otp, log=print) -> None:
    """Navigate the privacy portal and request the MI Fitness data copy."""
    page.goto(config.PRIVACY_URL, wait_until="networkidle", timeout=45000)
    time.sleep(2)
    resolve_auth(page, email, password, otp, log)
    time.sleep(2)
    try:
        page.get_by_role("button", name=re.compile(r"I've read", re.I)).first.click(timeout=4000)
    except Exception:
        pass
    time.sleep(1)
    page.get_by_role("button", name=re.compile(r"Manage your data", re.I)).first.click(timeout=8000)
    time.sleep(3)
    resolve_auth(page, email, password, otp, log)
    time.sleep(2)
    for _ in range(20):
        if page.evaluate("""()=>[...document.querySelectorAll('button')]
                .filter(b=>(b.getAttribute('title')||'').trim()==='Download a copy').length"""):
            break
        time.sleep(0.5)
    res = _click_product_download(page, config.PRODUCT_LABEL)
    if res != "clicked":
        raise RuntimeError(f"could not request the download ({res})")
    time.sleep(4)
    resolve_auth(page, email, password, otp, log)
    if not _confirm_download_modal(page, log):
        raise RuntimeError("could not confirm the 'Download a copy' modal")
    time.sleep(2)
    log("  request confirmed")


# ----------------------------------------------------------------- download
def download_files(page, url: str, out_zip: Path, email: str, password: str, otp, log=print) -> list[Path]:
    """Open the download URL (SSO login may need captcha/OTP), then click each 'File #N'."""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    page.goto(url, wait_until="networkidle", timeout=45000)
    resolve_auth(page, email, password, otp, log, timeout=200)
    appeared = False
    for _ in range(25):
        if page.get_by_text("File #1", exact=False).count():
            appeared = True
            break
        time.sleep(1)
    if not appeared:
        raise RuntimeError("download page did not show 'File #1'")
    for idx in range(1, 11):
        loc = page.get_by_text(f"File #{idx}", exact=False)
        if not loc.count():
            break
        target = out_zip if idx == 1 else out_zip.with_name(f"{out_zip.stem}_{idx}{out_zip.suffix}")
        with page.expect_download(timeout=90000) as di:
            loc.first.click()
        di.value.save_as(str(target))
        saved.append(target)
        log(f"  downloaded {target.name} ({target.stat().st_size} bytes)")
    return saved
