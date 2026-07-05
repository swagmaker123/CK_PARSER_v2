import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.expanduser("~"), ".openclaw", ".env"))

from cli import main


if __name__ == "__main__":
    main()
