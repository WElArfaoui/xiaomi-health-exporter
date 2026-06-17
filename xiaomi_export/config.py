"""Configuration: public Xiaomi endpoints/regex (not secret) + user settings."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

# --- Xiaomi web endpoints (public) ---
LOGIN_URL = "https://account.xiaomi.com/pass/serviceLogin?_locale=en_US"
ACCOUNT_HOME_URL = "https://account.xiaomi.com/fe/service/account?_locale=en_US"
PRIVACY_URL = "https://account.xiaomi.com/fe/service/account/privacy?_locale=en_US"
PRODUCT_LABEL = "MI Fitness"          # product shown in the "Manage your data" page

# --- Verification e-mails sent by Xiaomi (public facts) ---
XIAOMI_SENDER = "noreply@notice.xiaomi.com"
OTP_SUBJECTS = ["Xiaomi Account verification", "Verificacion de Cuenta Mi",
                "Verificación de Cuenta Mi"]
OTP_REGEX = r"(?<!\d)(\d{6})(?!\d)"
DOWNLOAD_SUBJECT = "Copy of personal data"
DOWNLOAD_URL_REGEX = r"https?://tools\.privacy\.mi\.com/userRight/downloadPrivacyInfo[^\s\"'<>]+"
# The decryption password for the ZIP is given inside the same e-mail.
DOWNLOAD_PASSWORD_REGEX = r"password to access the file is as follows:\s*([A-Za-z0-9]{8,40})"

# --- Timeouts (seconds) ---
OTP_WAIT_TIMEOUT = 180
LOGIN_TIMEOUT = 360


@dataclass
class Settings:
    """User-tunable settings (no secrets stored here)."""
    output_dir: Path = Path("./xiaomi_data")
    # Where login sessions are persisted (so captcha is only solved once per account):
    sessions_dir: Path = Path("./.sessions")
    headless: bool = False          # False = visible window (needed to solve captcha)
    # OTP / verification-code source: "manual" (you type it) or "imap" (read automatically)
    otp_mode: str = "manual"
    imap_host: str = ""             # only for otp_mode="imap"
    imap_port: int = 993

    def ensure_dirs(self) -> None:
        self.output_dir = Path(self.output_dir).expanduser()
        self.sessions_dir = Path(self.sessions_dir).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
