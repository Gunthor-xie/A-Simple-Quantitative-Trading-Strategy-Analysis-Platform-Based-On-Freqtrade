from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path


logger = logging.getLogger("freqtrade-desktop.security")


class SecretUnavailable(Exception):
    """Secret could not be stored or retrieved by any backend."""


def _env_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return f"FTDESK_SECRET_{safe}"


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows Data Protection API; raises if unavailable in this context."""
    import win32crypt

    if protect:
        return win32crypt.CryptProtectData(data, "freqtrade-desktop", None, None, None, 0)
    unprotected, _ = win32crypt.CryptUnprotectData(data, None, None, None, 0)
    return unprotected


class SecretStore:
    """Secret storage with layered backends:

    1. OS keyring (Windows Credential Manager) - preferred;
    2. ``FTDESK_SECRET_*`` environment variable;
    3. local vault file under the backend data dir (DPAPI-encrypted when the
       current process can use DPAPI; otherwise base64-obfuscated with a
       warning). The vault holds only the local bot api_server password, never
       exchange API keys (those stay in the freqtrade process environment).
    """

    SERVICE = "freqtrade-desktop"

    def __init__(self) -> None:
        self._keyring = None
        try:
            import keyring  # type: ignore

            self._keyring = keyring
        except Exception:
            self._keyring = None

    @property
    def available(self) -> bool:
        return self._keyring is not None

    @property
    def vault_path(self) -> Path:
        from .config import settings

        return Path(settings.db_path).parent / "secrets.vault.json"

    def _vault_store(self, name: str, value: str) -> None:
        raw = value.encode("utf-8")
        marker = "plain"
        try:
            encoded = _dpapi(raw, protect=True)
            payload = b"dpapi:" + base64.b64encode(encoded)
        except Exception:
            payload = b"plain:" + base64.b64encode(raw)
            logger.warning("DPAPI unavailable in this process; vault entry for %s is obfuscated only", name)
        path = self.vault_path
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[name] = payload.decode("ascii")
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _vault_read(self, name: str) -> str | None:
        path = self.vault_path
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        entry = data.get(name)
        if not entry:
            return None
        try:
            if entry.startswith("dpapi:"):
                decoded = base64.b64decode(entry[len("dpapi:") :])
                return _dpapi(decoded, protect=False).decode("utf-8")
            if entry.startswith("plain:"):
                return base64.b64decode(entry[len("plain:") :]).decode("utf-8")
        except Exception as exc:
            logger.warning("Failed to decrypt vault entry %s: %s", name, exc)
        return None

    def set(self, name: str, value: str) -> None:
        if self._keyring is not None:
            try:
                self._keyring.set_password(self.SERVICE, name, value)
                return
            except Exception:
                pass
        try:
            self._vault_store(name, value)
            return
        except Exception as exc:
            logger.warning("Vault write failed for %s: %s", name, exc)
        raise SecretUnavailable(
            "System keyring and local vault unavailable; provide the secret via "
            f"environment variable {_env_name(name)}"
        )

    def get(self, name: str) -> str:
        if self._keyring is not None:
            try:
                value = self._keyring.get_password(self.SERVICE, name)
                if value:
                    return value
            except Exception:
                pass
        env_value = os.environ.get(_env_name(name))
        if env_value:
            return env_value
        vault_value = self._vault_read(name)
        if vault_value:
            return vault_value
        raise SecretUnavailable(
            f"Secret {name} not found: store it in the system keyring, "
            f"set environment variable {_env_name(name)}, or use the app UI to save it"
        )

    def delete(self, name: str) -> None:
        if self._keyring is not None:
            try:
                self._keyring.delete_password(self.SERVICE, name)
            except Exception:
                pass
        path = self.vault_path
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data.pop(name, None)
                path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass


secret_store = SecretStore()
