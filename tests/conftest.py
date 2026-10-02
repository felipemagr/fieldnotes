import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(Path(__file__).parent))  # tests import their doubles from fakes.py


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
