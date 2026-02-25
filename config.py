# config.py
# FACADE for the new config/ directory
# This file ensures backward compatibility.

from config.system import *
from config.trading import *

# Re-exporting everything implies that 'import config as cfg' work as before.
