"""AutoClick local AI service."""

import sys
from pathlib import Path

# Ensure adjacent Autoclick-MCP package is importable regardless of how python is launched
_mcp_path = Path(__file__).resolve().parent.parent.parent / "Autoclick-MCP"
if _mcp_path.exists() and str(_mcp_path) not in sys.path:
    sys.path.insert(0, str(_mcp_path))
