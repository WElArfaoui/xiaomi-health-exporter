"""Load accounts from a CSV file.

CSV columns (header required):  email,password[,imap_password,label]
  email          Xiaomi account e-mail
  password       Xiaomi account password
  imap_password  (optional) mailbox password, if different from the Xiaomi password
  label          (optional) folder name; defaults to the e-mail local part

Keep this file private and secured (it contains passwords in clear text).
"""
from __future__ import annotations
import csv
from pathlib import Path

from .exporter import Account


def load_csv(path: str | Path) -> list[Account]:
    accounts: list[Account] = []
    with Path(path).open(newline="") as f:
        for row in csv.DictReader(f):
            email = (row.get("email") or "").strip()
            if not email:
                continue
            accounts.append(Account(
                email=email,
                password=(row.get("password") or "").strip(),
                imap_password=(row.get("imap_password") or "").strip(),
                label=(row.get("label") or "").strip(),
            ))
    return accounts
