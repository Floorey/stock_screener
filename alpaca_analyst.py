import os
import sys
import logging
import cmd
import argparse
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Try to import alpaca-py SDK
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetOrdersRequest, GetPortfolioHistoryRequest
    from alpaca.trading.enums import OrderStatus, QueryOrderStatus
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("alpaca_analyst.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("AlpacaAnalyst")

class AlpacaAnalyst:
    """Core class for Alpaca API interaction using alpaca-py SDK."""
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("APCA_API_KEY_ID")
        self.api_secret = os.getenv("APCA_API_SECRET_KEY")
        self.base_url = os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
        
        self.client = None
        self.is_connected = False
        
        if not SDK_AVAILABLE:
            logger.error("alpaca-py SDK not found. Please run 'pip install alpaca-py'.")
            return

        if not self.api_key or not self.api_secret:
            logger.error("API Keys missing. Ensure APCA_API_KEY_ID and APCA_API_SECRET_KEY are in .env")
            return

        try:
            # Paper trading is usually the default, but we use the base_url from env
            self.client = TradingClient(self.api_key, self.api_secret, paper=True, url_override=self.base_url)
            # Verify connection by getting account info
            account = self.client.get_account()
            self.is_connected = True
            logger.info(f"Connected to Alpaca. Account Status: {account.status}, Currency: {account.currency}")
        except Exception as e:
            logger.error(f"Failed to connect to Alpaca: {e}")
            self.is_connected = False

    def get_positions(self):
        """Fetch current positions and return as Pandas DataFrame."""
        if not self.is_connected:
            logger.warning("Not connected to Alpaca.")
            return pd.DataFrame()
        try:
            positions = self.client.get_all_positions()
            if not positions:
                return pd.DataFrame()
            
            # Convert list of Position objects to list of dicts
            data = []
            for p in positions:
                # alpaca-py objects have a __dict__ but better to access attributes
                data.append({
                    'symbol': p.symbol,
                    'qty': float(p.qty),
                    'avg_entry_price': float(p.avg_entry_price),
                    'current_price': float(p.current_price),
                    'market_value': float(p.market_value),
                    'unrealized_pl': float(p.unrealized_pl),
                    'unrealized_plpc': float(p.unrealized_plpc) * 100, # Percentage
                    'change_today': float(p.change_today) * 100
                })
            return pd.DataFrame(data)
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return pd.DataFrame()

    def get_trades(self, symbol=None, start_date=None, end_date=None):
        """Fetch historical trades (orders) and return as Pandas DataFrame."""
        if not self.is_connected:
            logger.warning("Not connected to Alpaca.")
            return pd.DataFrame()
        
        try:
            filter_params = {
                'status': QueryOrderStatus.ALL,
                'nested': True
            }
            if symbol:
                filter_params['symbols'] = [symbol]
            if start_date:
                filter_params['after'] = datetime.strptime(start_date, '%Y-%m-%d')
            if end_date:
                filter_params['until'] = datetime.strptime(end_date, '%Y-%m-%d')
            
            request_params = GetOrdersRequest(**filter_params)
            orders = self.client.get_orders(filter_params=request_params)
            
            if not orders:
                return pd.DataFrame()

            data = []
            for o in orders:
                data.append({
                    'id': o.id,
                    'symbol': o.symbol,
                    'qty': float(o.qty) if o.qty else 0,
                    'filled_qty': float(o.filled_qty) if o.filled_qty else 0,
                    'side': o.side.value,
                    'type': o.order_type.value,
                    'status': o.status.value,
                    'created_at': o.created_at,
                    'filled_at': o.filled_at,
                    'avg_fill_price': float(o.filled_avg_price) if o.filled_avg_price else 0
                })
            
            df = pd.DataFrame(data)
            if not df.empty:
                df['created_at'] = pd.to_datetime(df['created_at'])
                df['filled_at'] = pd.to_datetime(df['filled_at'])
            return df
        except Exception as e:
            logger.error(f"Error fetching trades: {e}")
            return pd.DataFrame()

class AlpacaCLI(cmd.Cmd):
    intro = 'Welcome to the Alpaca Analyst CLI. Type help or ? to list commands.\n'
    prompt = '(alpaca) '

    def __init__(self):
        super().__init__()
        self.analyst = AlpacaAnalyst()
        self.current_trades = pd.DataFrame()
        self.current_positions = pd.DataFrame()
        self.params = {
            'symbol': None,
            'start_date': (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),
            'end_date': datetime.now().strftime('%Y-%m-%d'),
            'export_format': 'csv'
        }

    def do_fetch_positions(self, arg):
        """Fetch current positions and display them."""
        print("Fetching positions...")
        self.current_positions = self.analyst.get_positions()
        if self.current_positions.empty:
            print("No positions found.")
        else:
            print(self.current_positions.to_string(index=False))
            print(f"\nTotal positions: {len(self.current_positions)}")

    def do_fetch_trades(self, arg):
        """Fetch trade history based on current parameters."""
        print(f"Fetching trades for {self.params['symbol'] or 'all symbols'} "
              f"from {self.params['start_date']} to {self.params['end_date']}...")
        
        self.current_trades = self.analyst.get_trades(
            symbol=self.params['symbol'],
            start_date=self.params['start_date'],
            end_date=self.params['end_date']
        )
        
        if self.current_trades.empty:
            print("No trades found.")
        else:
            # Display a summary
            display_cols = ['symbol', 'side', 'filled_qty', 'status', 'avg_fill_price', 'created_at']
            print(self.current_trades[display_cols].to_string(index=False))
            print(f"\nTotal trades fetched: {len(self.current_trades)}")

    def do_export(self, arg):
        """Export current data to file: export <trades|positions> [--format csv|json]"""
        args = arg.split()
        if not args:
            print("Usage: export <trades|positions> [--format csv|json]")
            return
        
        target = args[0]
        fmt = self.params['export_format']
        
        # Check for format override
        if '--format' in args:
            idx = args.index('--format')
            if idx + 1 < len(args):
                fmt = args[idx+1]

        df = None
        filename = ""
        
        if target == 'trades':
            df = self.current_trades
            filename = f"alpaca_trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        elif target == 'positions':
            df = self.current_positions
            filename = f"alpaca_positions_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        else:
            print(f"Invalid export target: {target}. Use 'trades' or 'positions'.")
            return

        if df is None or df.empty:
            print(f"No {target} data to export. Run fetch_{target} first.")
            return

        try:
            full_path = f"{filename}.{fmt}"
            if fmt == 'csv':
                df.to_csv(full_path, index=False)
            elif fmt == 'json':
                df.to_json(full_path, orient='records', indent=4)
            else:
                print(f"Unsupported format: {fmt}. Use csv or json.")
                return
            
            print(f"Successfully exported {len(df)} records to {full_path}")
        except Exception as e:
            print(f"Export failed: {e}")

    def do_status(self, arg):
        """Show connection status and current parameters."""
        status = "Connected" if self.analyst.is_connected else "Disconnected"
        print(f"Status: {status}")
        print(f"Base URL: {self.analyst.base_url}")
        print("Current Parameters:")
        for k, v in self.params.items():
            print(f"  {k}: {v}")

    def do_params(self, arg):
        """Set parameters: params <key> <value> (e.g., params symbol AAPL)"""
        args = arg.split()
        if len(args) != 2:
            print("Usage: params <key> <value>")
            return
        key, value = args
        if key in self.params:
            self.params[key] = value
            print(f"Set {key} to {value}")
        else:
            print(f"Invalid parameter: {key}. Available: {', '.join(self.params.keys())}")

    def do_exit(self, arg):
        """Exit the CLI."""
        print("Exiting...")
        return True

    def do_EOF(self, arg):
        """Exit the CLI using Ctrl+D."""
        print()
        return self.do_exit(arg)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Alpaca Analyst CLI Tool')
    parser.add_argument('--fetch', choices=['trades', 'positions'], help='Directly fetch and display data')
    parser.add_argument('--symbol', help='Symbol for trade fetch')
    parser.add_argument('--days', type=int, default=30, help='Days back for trade fetch')
    parser.add_argument('--export', choices=['csv', 'json'], help='Export format (if --fetch is used)')
    
    args = parser.parse_args()

    if not SDK_AVAILABLE:
        print("Error: alpaca-py SDK is not installed. Please install it with: pip install alpaca-py")
        sys.exit(1)
    
    cli = AlpacaCLI()
    
    if args.fetch:
        # Non-interactive mode
        if args.symbol:
            cli.do_params(f"symbol {args.symbol}")
        if args.days:
            start_date = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')
            cli.do_params(f"start_date {start_date}")
        
        if args.fetch == 'positions':
            cli.do_fetch_positions("")
            if args.export:
                cli.do_params(f"export_format {args.export}")
                cli.do_export("positions")
        else:
            cli.do_fetch_trades("")
            if args.export:
                cli.do_params(f"export_format {args.export}")
                cli.do_export("trades")
    else:
        # Interactive mode
        cli.cmdloop()
