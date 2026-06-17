"""Verification-code (OTP) sources.

Xiaomi sends a 6-digit code by e-mail at several steps. Two ways to provide it:
  - ManualOtp: you simply type the code you received (no e-mail credentials needed).
  - ImapOtp:   the code is read automatically from your inbox over IMAP (for bulk runs).
"""
from __future__ import annotations
from .mailbox import Imap


class ManualOtp:
    """Prompts the user to type the code. Good for a single account."""

    def __init__(self, label: str = ""):
        self.label = label

    def prime(self) -> None:
        pass

    def get(self, timeout: int = 0) -> str:
        tag = f" ({self.label})" if self.label else ""
        return input(f"  -> Enter the verification code Xiaomi e-mailed you{tag}: ").strip()


class ImapOtp:
    """Reads the code automatically from the inbox. Needs IMAP access to that mailbox."""

    def __init__(self, imap: Imap):
        self.imap = imap
        self._baseline: dict[str, int] = {}

    def prime(self) -> None:
        # snapshot the mailbox BEFORE the code is requested, so we only accept newer ones
        self._baseline = self.imap.snapshot_uids()

    def get(self, timeout: int = 180) -> str:
        return self.imap.wait_for_otp(self._baseline, timeout=timeout)
