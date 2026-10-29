import os
import tempfile

# Set before importing any application module. Runtime files stay outside the repo
# and outside the user's normal application data, including during GUI tests.
TEST_DATA = tempfile.TemporaryDirectory(prefix='weekly-schedule-tests-')
os.environ['WEEKLY_SCHEDULE_DATA_DIR'] = TEST_DATA.name
