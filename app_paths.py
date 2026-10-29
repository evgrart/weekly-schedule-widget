"""Keep source code and private, per-user runtime data in separate directories."""
import os
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parent
_default = Path(os.environ.get('LOCALAPPDATA', Path.home()/'.local'/'share'))/'WeeklyScheduleWidgetPublic'
DATA_ROOT = Path(os.environ.get('WEEKLY_SCHEDULE_DATA_DIR', str(_default))).expanduser().resolve()
DATA_ROOT.mkdir(parents=True, exist_ok=True)

# Older modules use ROOT for runtime files. It never points to the checkout.
ROOT = DATA_ROOT
