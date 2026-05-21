"""Verify the production-default guard refuses to boot with shipped placeholders.

The lifespan-time check at `app.main._check_production_defaults` is the only thing
standing between a misconfigured prod deploy and an open admin endpoint /
forged-gateway-secret world. Pin its behavior.
"""

import pytest

from app.core.config import settings
from app.main import _check_production_defaults


def test_dev_environment_allows_dev_defaults(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "internal_secret", "dev-internal-secret-change-me")
    monkeypatch.setattr(settings, "admin_password", "admin")
    _check_production_defaults()  # should not raise


def test_production_refuses_default_internal_secret(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "internal_secret", "dev-internal-secret-change-me")
    monkeypatch.setattr(settings, "admin_password", "real-strong-pw")
    with pytest.raises(RuntimeError) as ei:
        _check_production_defaults()
    assert "INTERNAL_SECRET" in str(ei.value)


def test_production_refuses_default_admin_password(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "internal_secret", "real-strong-secret")
    monkeypatch.setattr(settings, "admin_password", "admin")
    with pytest.raises(RuntimeError) as ei:
        _check_production_defaults()
    assert "ADMIN_PASSWORD" in str(ei.value)


def test_production_lists_both_when_both_default(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "internal_secret", "dev-internal-secret-change-me")
    monkeypatch.setattr(settings, "admin_password", "admin")
    with pytest.raises(RuntimeError) as ei:
        _check_production_defaults()
    assert "INTERNAL_SECRET" in str(ei.value)
    assert "ADMIN_PASSWORD" in str(ei.value)


def test_production_with_real_values_boots(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "internal_secret", "real-strong-secret-xyz")
    monkeypatch.setattr(settings, "admin_password", "real-strong-password-xyz")
    _check_production_defaults()  # should not raise
