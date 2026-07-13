import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

# Проектный .env — основной; ~/.openclaw/.env — опциональный fallback
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
load_dotenv(os.path.join(os.path.expanduser("~"), ".openclaw", ".env"), override=False)

from cli import main


if __name__ == "__main__":
    main()
