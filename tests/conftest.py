"""The tests run in English (the messages they look at are the English source texts)."""
import pytest

from worldbridge import i18n


@pytest.fixture(autouse=True)
def _english():
    i18n.set_language("en")
    yield
    i18n.set_language("en")
