"""Private state owned by model-reference maintenance."""

import os
from pathlib import Path

HOME = Path(os.environ.get("AGENT_MODELS_HOME") or
            Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "agent-models")
if not HOME.is_absolute():
    raise ValueError("AGENT_MODELS_HOME and XDG_STATE_HOME must be absolute")
