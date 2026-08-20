"""Keychain broker for private-beta credentials. Never returns secret bytes to logs."""

from __future__ import annotations

import subprocess

OPENROUTER_ACCOUNT = "OPENROUTER_API"
OPENROUTER_SERVICE = "newsroom.shadow.v1"


class BrokerError(RuntimeError):
    """Credential injection failed closed."""


def _keychain_password(*, account: str, service: str) -> str:
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            account,
            "-s",
            service,
            "-w",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise BrokerError(f"Keychain class {account} is absent")
    secret = result.stdout.strip()
    if not secret:
        raise BrokerError(f"Keychain class {account} is empty")
    return secret


def openrouter_api_key() -> str:
    return _keychain_password(account=OPENROUTER_ACCOUNT, service=OPENROUTER_SERVICE)
