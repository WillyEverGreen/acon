"""Pytest configuration for acon test suite."""
import pytest


# Enable asyncio mode for pytest-asyncio
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
