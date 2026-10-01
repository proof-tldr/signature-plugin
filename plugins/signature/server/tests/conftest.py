"""Makes the server's modules importable by the tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
