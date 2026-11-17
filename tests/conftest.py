"""
Shared pytest configuration.

Runs BEFORE any test module imports the app, so the environment below is in
place when config/settings.py reads it:

* AGRISENSE_DATA_DIR -> a throw-away folder. Tests used to write history and
  farm-profile files into the real ./data directory; now they never touch it.
* LLM_API_KEY / SITE_URL -> blank, so a developer's real `.env` can never make
  a test call a live LLM (spending real quota) or change expected URLs.
* AGRISENSE_RATE_LIMIT=0 -> the request-heavy suite is not throttled. The
  rate-limit tests switch it back on explicitly.
"""
import os
import shutil
import tempfile

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="agrisense-test-data-")
os.environ["AGRISENSE_DATA_DIR"] = _TEST_DATA_DIR
os.environ["LLM_API_KEY"] = ""
os.environ["SITE_URL"] = ""
os.environ["AGRISENSE_RATE_LIMIT"] = "0"
os.environ["AGRISENSE_ENV"] = "development"


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)
