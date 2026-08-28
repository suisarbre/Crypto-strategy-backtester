
import os

# 1. API Keys & Secrets
try:
    # Try importing from the root secret_keys first (backward compatibility)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from secret_keys import API_KEY, SECRET_KEY
except ImportError:
    # Optional. The bot only calls PUBLIC CCXT endpoints (fetch_ohlcv,
    # fetch_ticker), which require no authentication — see ADR-002; there is no
    # order-execution code. Credentials would only be needed if a live path is
    # built. data_loader omits them entirely when they are blank.
    API_KEY = ''
    SECRET_KEY = ''

# 2. System Paths & Settings
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
PARAMS_FILE_PATH = "best_params.json" 

# 3. Logging & Debug
LOG_LEVEL = "INFO"

# 4. Global Optimization Settings
OPTIMIZE_INTERVAL_MINUTES = 240 
WFA_ENABLED = False
WFA_WINDOW_SIZE = 15000       
WFA_TRAIN_RATIO = 0.7         

# [Rolling WFA] Walk-Forward Analysis Rolling Windows (per Architecture Report)
WFA_ROLLING_ENABLED = True     # Use rolling windows instead of single IS/OOS split
WFA_TRAIN_BARS = 8000          # Training window size (bars)
WFA_TEST_BARS = 2000           # Test/validation window size (bars)
WFA_STEP_BARS = 1000           # Step between windows (overlap control)

# [PSO] Particle Swarm Optimization (per Architecture Report)
USE_PSO = True                 # Use PSO instead of grid search
PSO_SWARM_SIZE = 50            # Number of particles in swarm
PSO_MAX_ITERATIONS = 30        # PSO generations
PSO_FALLBACK_TO_GRID = True    # Fall back to grid search if PSO unavailable

# 5. Dashboard Settings
DASHBOARD_PORT = 8088
DASHBOARD_TITLE = 'TradeBot Dashboard'
AUTO_OPTIMIZE_ON_START = False       # Run optimization when dashboard first loads
CHART_UPDATE_INTERVAL_SEC = 10.0     # Live chart polling interval (seconds)
CHART_LIVE_FETCH_LIMIT = 300         # Bars to fetch for live chart updates
BACKGROUND_LOOP_INTERVAL_SEC = 1.0   # Background trading loop interval
