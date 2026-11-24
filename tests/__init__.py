
import os

os.environ.setdefault("PTB_RAISE", "1")   # app.guarded() re-raises, so a broken tab fails the tests
# The regulation the tests' expectations were written against (a full season of tournaments and replays).
# Day one of a new regulation has its own tests (test_new_regulation.TestDayOne).
os.environ.setdefault("PTB_FORMAT", "gen9championsvgc2026regmc")
