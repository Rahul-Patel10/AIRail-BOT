"""Index stations from SQLite into ChromaDB for fuzzy station resolution."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bootstrap import ensure_station_index

if __name__ == "__main__":
    force = "--force" in sys.argv
    from database import init_db

    init_db()
    ensure_station_index(force=force)
