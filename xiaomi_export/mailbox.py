"""IMAP reader: verification codes (OTP) and the download e-mail (link + ZIP password).

New messages are detected by UID baseline (not by Date header): Xiaomi's mail server clock can
be skewed vs. the local clock, which makes date filtering drop the legitimate fresh code.
"""
from __future__ import annotations
import re
import time
import html
from imap_tools import MailBox, AND

from . import config


def _clean_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


class Imap:
    """Thin IMAP helper for one mailbox."""

    FOLDERS = ["INBOX", "INBOX.spam", "INBOX.Junk", "Junk", "Spam"]

    def __init__(self, host: str, port: int, user: str, password: str):
        self.host, self.port, self.user, self.password = host, port, user, password

    def _box(self) -> MailBox:
        return MailBox(self.host, self.port).login(self.user, self.password)

    def snapshot_uids(self) -> dict[str, int]:
        """Max Xiaomi-sender UID per folder, taken before triggering a code (baseline)."""
        snap: dict[str, int] = {}
        with self._box() as mb:
            for folder in self.FOLDERS:
                try:
                    mb.folder.set(folder)
                except Exception:
                    continue
                uids = [int(m.uid) for m in mb.fetch(AND(from_=config.XIAOMI_SENDER),
                        reverse=True, limit=50, mark_seen=False) if m.uid]
                snap[folder] = max(uids) if uids else 0
        return snap

    def _scan(self, baseline: dict[str, int], matcher, extractor):
        with self._box() as mb:
            for folder in self.FOLDERS:
                try:
                    mb.folder.set(folder)
                except Exception:
                    continue
                base = baseline.get(folder, 0)
                for msg in mb.fetch(AND(from_=config.XIAOMI_SENDER), reverse=True,
                                    limit=15, mark_seen=False):
                    if msg.uid and int(msg.uid) <= base:
                        continue
                    if not matcher(msg.subject or ""):
                        continue
                    val = extractor(msg.text or "", msg.html or "")
                    if val:
                        return val
        return None

    def wait_for_otp(self, baseline: dict[str, int],
                     timeout: int = config.OTP_WAIT_TIMEOUT, poll: int = 5) -> str:
        def matcher(subj: str) -> bool:
            return any(s.lower() in subj.lower() for s in config.OTP_SUBJECTS) or "verif" in subj.lower()

        def extractor(text: str, raw_html: str):
            m = re.search(config.OTP_REGEX, text or _clean_html(raw_html))
            return m.group(1) if m else None

        deadline = time.time() + timeout
        while time.time() < deadline:
            code = self._scan(baseline, matcher, extractor)
            if code:
                return code
            time.sleep(poll)
        raise TimeoutError(f"No verification code arrived for {self.user} in {timeout}s")

    def find_download(self, baseline: dict[str, int]):
        """Return {'url':..., 'password':...} once the download e-mail arrives, else None."""
        def matcher(subj: str) -> bool:
            return config.DOWNLOAD_SUBJECT.lower() in subj.lower()

        def extractor(text: str, raw_html: str):
            blob = raw_html or text
            m = re.search(config.DOWNLOAD_URL_REGEX, blob)
            if not m:
                return None
            src = (text or "") + " " + _clean_html(raw_html)
            mp = re.search(config.DOWNLOAD_PASSWORD_REGEX, src)
            return {"url": m.group(0).replace("&amp;", "&"),
                    "password": mp.group(1) if mp else None}

        return self._scan(baseline, matcher, extractor)
