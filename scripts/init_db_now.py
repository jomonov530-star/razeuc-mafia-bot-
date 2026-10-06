import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path so `app` imports work when run as a script
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import init_db


if __name__ == '__main__':
    asyncio.run(init_db())
    print('init_db completed')
