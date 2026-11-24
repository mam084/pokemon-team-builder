
import os

os.environ.setdefault("PTB_RAISE", "1")   # app.guarded() re-raises, so a broken tab fails the tests
