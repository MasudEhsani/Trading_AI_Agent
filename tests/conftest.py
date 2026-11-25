# conftest.py - runs before the tests are imported. Points all data at a temporary
# folder, so running the tests never creates or touches data/live/paper.db.
import os
import tempfile

os.environ["TRADING_DATA_DIR"] = tempfile.mkdtemp(prefix="trading_agent_tests_")
