import argparse
import sys
import os
import config as cfg

# Optimization Imports (lightweight, no side effects)
from core.optimizer import execute_smart_optimization
import glob

def run_bot(args):
    """
    Starts the Paper Trading Bot.
    """
    # Refuse loudly rather than silently running paper: the flag used to be
    # parsed and discarded, which described the bot as something it is not.
    if getattr(args, 'live', False):
        print("Error: --live is not implemented. The bot is paper-only — there is no "
              "order-execution code (see docs/decisions/ADR-002-live-execution.md).")
        sys.exit(1)

    # Lazy imports: These modules have heavy side effects (NiceGUI binds ports,
    # dashboard.py hijacks stdout, PaperTrader connects to exchange).
    # Only load them when actually running the bot.
    from core.trader import PaperTrader
    import utils
    import schedule
    from nicegui import ui
    from gui.dashboard import dashboard
    
    print(f"=== Lorentzian Bot via CLI ===")
    
    # 1. Apply Patches & Setup
    utils.apply_patches()
    
    # 2. Initialize Trader
    bot = PaperTrader()
    
    # 3. Connect Dashboard
    dashboard.set_bot(bot)
    
    print(f"Open Browser at http://localhost:{cfg.DASHBOARD_PORT}")
    
    # 4. Schedule
    schedule.every(cfg.OPTIMIZE_INTERVAL_MINUTES).minutes.do(bot.run_optimization_thread)
    
    # 5. Start UI
    # Note: ui.run blocks execution
    try:
        ui.run(title=cfg.DASHBOARD_TITLE, dark=True, port=cfg.DASHBOARD_PORT, reload=False)
    except KeyboardInterrupt:
        print("\n[CLI] Caught Ctrl+C. Shutting down...")
        if bot: bot.kill_switch()
        sys.exit(0)

def run_optimization(args):
    """
    Runs Strategy Optimization (Single or Multi-Strategy).
    """
    print("\n=== Strategy Optimization Tool ===")
    
    # Base Config
    current_config = cfg.CURRENT_CONFIG.copy()
    current_config['symbol'] = cfg.SYMBOL
    current_config['timeframe'] = args.timeframe if args.timeframe else cfg.TIMEFRAME
    
    # Inject Test Ranges if available
    if hasattr(cfg, 'LEVERAGE_TEST_RANGE'):
        current_config['leverage_range'] = cfg.LEVERAGE_TEST_RANGE

    # -- Multi-Strategy Mode --
    if args.multi:
        repo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'strategies', 'repository')
        if not os.path.exists(repo_path):
            print(f"Error: Repository not found at {repo_path}")
            return

        strategy_files = glob.glob(os.path.join(repo_path, "*.json"))
        if not strategy_files:
            print(f"No strategy files found in {repo_path}")
            return
            
        print(f"Found {len(strategy_files)} strategies: {[os.path.basename(f) for f in strategy_files]}")
        results = []

        for strat_file in strategy_files:
            strat_name = os.path.basename(strat_file)
            print(f"\n" + "="*50)
            print(f" >> Optimizing Strategy: {strat_name}")
            print("="*50)
            
            # Run Optimization
            opt_res = execute_smart_optimization(current_config.copy(), strategy_path=strat_file)
            
            if opt_res:
                best_params, wins, trades, mdd, balance, score = opt_res
                wr = (wins / trades * 100) if trades > 0 else 0.0
                results.append({
                    "Strategy": strat_name,
                    "Score": score,
                    "Net Profit": balance - current_config.get('start_balance', 100.0),
                    "Win Rate %": wr,
                    "Trades": trades,
                    "MDD %": mdd * 100
                })
            else:
                 results.append({"Strategy": strat_name, "Score": -1})

        # Display Comparison
        print(f"\n" + "="*80)
        print(" >> Multi-Strategy Comparison Results")
        print("="*80)
        print(f"{'Strategy':<25} | {'Score':<10} | {'Net Profit':<12} | {'Win Rate %':<12} | {'Trades':<8} | {'MDD %':<8}")
        print("-" * 80)
        
        if results:
            results.sort(key=lambda x: x.get('Score', -1), reverse=True)
            for r in results:
                if r['Score'] != -1:
                    print(f"{r['Strategy']:<25} | {r['Score']:<10.2f} | {r['Net Profit']:<12.2f} | {r['Win Rate %']:<12.2f} | {r['Trades']:<8} | {r['MDD %']:<8.2f}")
                else:
                    print(f"{r['Strategy']:<25} | {'FAILED':<10}")
            print("-" * 80)

    # -- Single Strategy Mode --
    else:
        # Determine Path
        if args.strategy:
             # Check if it's a file path or just a name in repository
             if os.path.exists(args.strategy):
                 strat_path = args.strategy
             else:
                 # Check repository
                 repo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'strategies', 'repository', args.strategy)
                 if os.path.exists(repo_path):
                     strat_path = repo_path
                 elif os.path.exists(repo_path + ".json"):
                     strat_path = repo_path + ".json"
                 else:
                     print(f"Error: Strategy '{args.strategy}' not found.")
                     return
        else:
            # Default
            strat_path = None # Will use core/optimizer.py default logic (strategies/strategies.json)

        print(f"Optimizing Single Strategy: {strat_path if strat_path else 'Default (Active)'}")
        execute_smart_optimization(current_config, strategy_path=strat_path)


def main():
    parser = argparse.ArgumentParser(description="Lorentzian Bot Unified CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: run
    parser_run = subparsers.add_parser("run", help="Start the Trading Bot (Live/Paper)")
    parser_run.add_argument("--live", action="store_true",
                            help="Not implemented — the bot is paper-only and has no order code "
                                 "(see docs/decisions/ADR-002-live-execution.md)")
    
    # Command: optimize
    parser_opt = subparsers.add_parser("optimize", help="Run Strategy Optimization")
    parser_opt.add_argument("--multi", action="store_true", help="Run optimization on all strategies in repository")
    parser_opt.add_argument("--strategy", type=str, help="Specific strategy file name or path")
    parser_opt.add_argument("--timeframe", type=str, help="Override timeframe (e.g., 5m, 15m)")

    # Command: dashboard (Alias for run)
    parser_dash = subparsers.add_parser("dashboard", help="Start the Dashboard (Alias for run)")

    args = parser.parse_args()

    if args.command == "run" or args.command == "dashboard":
        run_bot(args)
    elif args.command == "optimize":
        run_optimization(args)
    else:
        # Default behavior: Print help
        parser.print_help()

if __name__ == "__main__":
    main()
