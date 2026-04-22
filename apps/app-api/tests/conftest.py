from pathlib import Path
import sys


APP_API_ROOT = Path(__file__).resolve().parents[1]

if str(APP_API_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_API_ROOT))
