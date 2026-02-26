"""
===============================================================================
NIFTY 50 OPTIONS ORB (OPENING RANGE BREAKOUT) STRATEGY
===============================================================================

Author: Trading Strategy Bot
Version: 1.0
Description: Opening Range Breakout strategy for Nifty 50 options using 
             Upstox API for live market data

Strategy Logic:
1. Opening Range: First 15 minutes (9:15 AM - 9:30 AM)
2. Breakout Detection: 
   - Price > ORB High → Buy CALL option
   - Price < ORB Low → Buy PUT option
3. Risk Management:
   - Entry: ATM (At-The-Money) option
   - Stop Loss: 20% below entry
   - Target: 40% above entry

⚠️  DISCLAIMER: This code is for educational purposes only. Trading involves
    substantial risk of loss. Always test thoroughly before live trading.

===============================================================================
"""

import time
import datetime
from datetime import datetime as dt, timedelta
import requests
import logging
from typing import Dict, Optional, List
from urllib.parse import quote
import pandas as pd
import csv
import json
import os

# ============================================================================
# CONFIGURATION SECTION - MODIFY THESE VALUES
# ============================================================================

CONFIG = {
    # Upstox API Credentials
    # Live Token (Required for Market Data & Quotes)
    'ACCESS_TOKEN': 'eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI1NUJBOVgiLCJqdGkiOiI2OTlmYmZmMzVjNTdjODY5OTEwOTQwNTMiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc3MjA3NzA0MywiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzcyMTQzMjAwfQ.2E8d3YOSEjvDBabg2LqOxEgi0I66Tpm3-E2uXXTpano',
    
    # Sandbox Token (Required if USE_SANDBOX_API is True for Orders)
    'SANDBOX_TOKEN': 'eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI1NUJBOVgiLCJqdGkiOiI2OTljMTk5ODk1M2M5YjFjMDIxNjRjMzAiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaWF0IjoxNzcxODM3ODQ4LCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE3NzQzODk2MDB9.2pU16hshwl2MEdLtm8h3XOc6axRlCTmAO0VSKtnYhbo',
    
    # Trading Parameters
    # EXPIRY_DATE auto-calculated for Tuesday (Nifty weekly expiry)
    'LOT_SIZE': 65,           # Nifty option lot size (verify current size)
    
    # ORB Parameters
    'ORB_MINUTES': 15,        # Opening range duration in minutes
    'ORB_START_TIME': '09:15',
    'ORB_END_TIME': '09:30',
    'ORB_BUFFER_POINTS': 10,  # Points required beyond ORB High/Low to confirm breakout
    
    # Risk Management
    # SL/Target are now purely ATR based
    
    # Rs-Based Risk Management
    'PROFIT_TARGET_RS': 1000,
    'TRAILING_STEP_RS': 500,
    'PROFIT_LOCK_ACTIVATION_RS': 700,
    'PROFIT_LOCK_AMOUNT_RS': 350,
    'INITIAL_STOP_LOSS_RS': -1000,

    
    # -------------------------------------------------------------------------
    # IMPROVED RISK MANAGEMENT
    # -------------------------------------------------------------------------
    'MAX_TRADES_PER_DAY': 1,    # Stop after 1 trades (Win or Loss)
    'MAX_DAILY_LOSS': 1000,     # Stop trading if cumulative loss exceeds ₹1000
    # -------------------------------------------------------------------------
    
    # Execution
    'EXECUTE_TRADES': False,   # Set to True for live trading, False for paper trading
    'USE_SANDBOX_API': True,   # Set to True to use Upstox Sandbox (https://api-sandbox.upstox.com)
    
    # Reporting
    'CSV_FILENAME': 'trades/trades.csv',
    'DISCORD_WEBHOOK_URL': 'https://discord.com/api/webhooks/1412386951474057299/Jgft_nxzGxcfWOhoLbSWMde-_bwapvqx8l3VQGQwEoR7_8n4b9Q9zN242kMoXsVbLdvG',
    
    # Logging
    'LOG_LEVEL': 'INFO',      # DEBUG, INFO, WARNING, ERROR
}

# ============================================================================
# LOGGING SETUP
# ============================================================================

import sys
import io

# Create directories for logs and trades if they don't exist
os.makedirs('logs', exist_ok=True)
os.makedirs('trades', exist_ok=True)

# Force UTF-8 encoding on Windows BEFORE setting up logging
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Custom IST Time for Logging
def ist_converter(*args):
    utc_dt = datetime.datetime.now(datetime.UTC)
    ist_dt = utc_dt + datetime.timedelta(hours=5, minutes=30)
    return ist_dt.timetuple()

logging.Formatter.converter = ist_converter

# Configure logging with UTF-8 encoding for console output
file_handler = logging.FileHandler(
    f'logs/nifty_orb_{dt.now().strftime("%Y%m%d_%H%M%S")}.log',
    encoding='utf-8'
)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %I:%M:%S %p'))

# StreamHandler with UTF-8 encoding for Windows compatibility
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %I:%M:%S %p'))

logging.basicConfig(
    level=getattr(logging, CONFIG['LOG_LEVEL']),
    handlers=[file_handler, stream_handler]
)
logger = logging.getLogger(__name__)

# ============================================================================
# UPSTOX API WRAPPER CLASS
# ============================================================================

class UpstoxAPI:
    """Wrapper class for Upstox API interactions"""
    
    def __init__(self, access_token: str, sandbox_token: str = None, use_sandbox: bool = False):
        """
        Initialize Upstox API client
        
        Args:
            access_token: Upstox LIVE API access token (For Quotes & Data)
            sandbox_token: Upstox SANDBOX access token (For Orders)
            use_sandbox: Use sandbox environment
        """
        self.access_token = access_token
        self.sandbox_token = sandbox_token
        self.use_sandbox = use_sandbox
        self.base_url = "https://api.upstox.com/v2"
        self.sandbox_url = "https://api-sandbox.upstox.com/v2"
        
        # Headers for Live endpoints
        self.headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.access_token}'
        }
        
        # Headers for Sandbox endpoints
        self.sandbox_headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.sandbox_token}' if self.sandbox_token else ''
        }
        logger.info(f"Upstox API initialized (Sandbox Enabled for Orders: {self.use_sandbox})")
    
    def get_quote(self, symbol: str) -> Optional[Dict]:
        """
        Get live market quote for a symbol
        
        Args:
            symbol: Trading symbol or instrument key (e.g., "NSE_INDEX|Nifty 50" or "NSE_FO|42536")
        
        Returns:
            Dictionary containing quote data or None
        """
        try:
            url = f"{self.base_url}/market-quote/quotes"
            params = {'symbol': symbol}
            
            response = requests.get(
                url, 
                headers=self.headers, 
                params=params, 
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('status') == 'success':
                    response_data = data.get('data', {})
                    
                    # Try multiple key formats
                    # 1. Exact match with pipe
                    quote_data = response_data.get(symbol)
                    
                    # 2. Try with colon separator
                    if not quote_data:
                        symbol_with_colon = symbol.replace('|', ':')
                        quote_data = response_data.get(symbol_with_colon)
                    
                    # 3. Try any key that contains the instrument number
                    if not quote_data and '|' in symbol:
                        instrument_num = symbol.split('|')[-1]
                        for key in response_data.keys():
                            if instrument_num in key or key.endswith(instrument_num):
                                quote_data = response_data.get(key)
                                logger.debug(f"✓ Found quote using alternate key: {key}")
                                break
                    
                    # 4. If still not found, just return the first quote data
                    if not quote_data and response_data:
                        first_key = list(response_data.keys())[0]
                        quote_data = response_data[first_key]
                        logger.debug(f"✓ Using first available quote: {first_key}")
                    
                    if quote_data:
                        return quote_data
                    else:
                        logger.error(f"❌ No quote data in response for {symbol}")
                        logger.error(f"Available keys: {list(response_data.keys())}")
                else:
                    logger.error(f"API returned error: {data.get('message')}")
            else:
                logger.error(f"HTTP {response.status_code}: {response.text[:500]}")
                # Common error codes
                if response.status_code == 401:
                    logger.error("🔒 Authentication failed - Token is invalid or expired")
                elif response.status_code == 403:
                    logger.error("🚫 Access forbidden - Check API permissions")
                elif response.status_code == 429:
                    logger.error("⏱️  Rate limit exceeded - Too many requests")
            
            return None
            
        except requests.exceptions.Timeout:
            logger.error("Request timeout while fetching quote")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in get_quote: {e}")
            return None
    
    def get_intraday_candles(self, symbol: str, unit: str = "minutes", 
                            interval: int = 1) -> Optional[List]:
        """
        Get intraday candle data for current trading day using V3 API
        
        Args:
            symbol: Trading symbol (e.g., "NSE_INDEX|Nifty 50")
            unit: Time unit - "minutes", "hours", or "days"
            interval: Interval value (1-300 for minutes, 1-2 for hours, 1-5 for days)
        
        Returns:
            List of candles or None
        """
        try:
            # URL encode the symbol (e.g., "NSE_INDEX|Nifty 50" -> "NSE_INDEX%7CNifty%2050")
            encoded_symbol = quote(symbol, safe='')
            
            # Format interval string (e.g., "1minute", "30minute")
            # Remove 's' from unit if present (minutes -> minute)
            unit_clean = unit.rstrip('s')
            interval_str = f"{interval}{unit_clean}"
            
            # V2 intraday endpoint (Standard)
            url = f"{self.base_url}/historical-candle/intraday/{encoded_symbol}/{interval_str}"
            
            response = requests.get(url, headers=self.headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('status') == 'success':
                    candles = data.get('data', {}).get('candles', [])
                    logger.info(f"Fetched {len(candles)} candles")
                    return candles
                else:
                    logger.error(f"API error: {data.get('message')}")
            else:
                logger.error(f"HTTP {response.status_code}: {response.text[:500]}")
                if response.status_code == 401:
                    logger.error("🔒 Authentication failed - Token is invalid or expired")
                elif response.status_code == 403:
                    logger.error("🚫 Access forbidden - Check API permissions")
                elif response.status_code == 404:
                    logger.error("❓ Resource not found - Check symbol format or V3 API availability")
            
            return None
            
        except Exception as e:
            logger.error(f"Error in get_intraday_candles: {e}")
            return None
    
    def get_historical_candles(self, symbol: str, interval: str, from_date: str, to_date: str) -> Optional[List]:
        """
        Get historical candle data
        
        Args:
            symbol: Trading symbol (e.g., "NSE_INDEX|Nifty 50")
            interval: Candle interval (1minute, 30minute, day, etc.)
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
        
        Returns:
            List of candles or None
        """
        try:
            encoded_symbol = quote(symbol, safe='')
            url = f"{self.base_url}/historical-candle/{encoded_symbol}/{interval}/{to_date}/{from_date}"
            
            response = requests.get(url, headers=self.headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    candles = data.get('data', {}).get('candles', [])
                    logger.info(f"Fetched {len(candles)} historical candles ({interval})")
                    return candles
                else:
                    logger.error(f"API error: {data.get('message')}")
            else:
                logger.error(f"HTTP {response.status_code}: {response.text[:500]}")
            
            return None
            
        except Exception as e:
            logger.error(f"Error in get_historical_candles: {e}")
            return None
    
    def place_order(self, symbol: str, quantity: int, 
                   transaction_type: str = 'BUY',
                   order_type: str = 'MARKET',
                   product: str = 'I',
                   price: float = 0.0,
                   trigger_price: float = 0.0) -> Optional[Dict]:
        """
        Place an order on Upstox
        
        Args:
            symbol: Trading symbol
            quantity: Order quantity
            transaction_type: BUY or SELL
            order_type: MARKET or LIMIT
            product: I (Intraday) or D (Delivery)
        
        Returns:
            Order response or None
        """
        try:
            url = f"{self.sandbox_url if self.use_sandbox else self.base_url}/order/place"
            
            payload = {
                'quantity': quantity,
                'product': product,
                'validity': 'DAY',
                'price': price,
                'tag': 'ORB_Strategy',
                'instrument_token': symbol,
                'order_type': order_type,
                'transaction_type': transaction_type,
                'disclosed_quantity': 0,
                'trigger_price': trigger_price,
                'is_amo': False
            }
            
            logger.info(f"Placing {transaction_type} order for {symbol}")
            
            response = requests.post(
                url, 
                headers=self.sandbox_headers if self.use_sandbox else self.headers, 
                json=payload, 
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('status') == 'success':
                    logger.info(f"✓ Order placed successfully: {result}")
                    return result
                else:
                    logger.error(f"Order rejected: {result.get('message')}")
            else:
                logger.error(f"Order failed: {response.status_code} - {response.text}")
            
            return None
            
        except Exception as e:
            logger.error(f"Exception in place_order: {e}")
            return None

    def modify_order(self, order_id: str, new_trigger_price: float, new_price: float) -> bool:
        """
        Modify an open trigger/SL order on Upstox.
        """
        try:
            url = f"{self.sandbox_url if self.use_sandbox else self.base_url}/order/modify"
            
            payload = {
                'order_id': order_id,
                'trigger_price': new_trigger_price,
                'price': new_price,
                'validity': 'DAY',
                'order_type': 'SL'
            }
            
            response = requests.put(
                url, 
                headers=self.sandbox_headers if self.use_sandbox else self.headers, 
                json=payload, 
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('status') == 'success':
                    logger.debug(f"✓ Order {order_id} modified successfully to Trigger: {new_trigger_price:.2f}")
                    return True
                else:
                    logger.error(f"Order modify rejected: {result.get('message')}")
            else:
                logger.error(f"Order modify failed: {response.status_code} - {response.text}")
            
            return False
            
        except Exception as e:
            logger.error(f"Exception in modify_order: {e}")
            return False
    
    def get_positions(self) -> Optional[Dict]:
        """Get current positions"""
        try:
            # Note: Sandbox may not support positions, defaulting to live to avoid crashing
            url = f"{self.base_url}/portfolio/short-term-positions"
            
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    return data['data']
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return None

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def encode_symbol(sym: str) -> str:
    """URL encode symbol for API calls"""
    return sym.replace('|', '%7C').replace(' ', '%20')

def get_ist_time() -> datetime.datetime:
    """Get current time in IST (UTC+5:30)"""
    utc_now = datetime.datetime.now(datetime.UTC)
    ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
    return ist_now

def get_next_weekly_expiry(weekday_target=1) -> str:
    """
    Returns next weekly expiry date (default: Tuesday for NIFTY 50)
    
    Args:
        weekday_target: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    
    Returns:
        Expiry date in YYMMDD format (e.g., '250206')
    """
    today = get_ist_time()
    
    
    # Calculate days until next target weekday
    days_ahead = (weekday_target - today.weekday()) % 7
    
    # If today is the expiry day
    if days_ahead == 0:
        # If before market close (3:30 PM), use today
        if today.hour < 15 or (today.hour == 15 and today.minute < 30):
            expiry = today
        else:
            # After market close, use next week
            expiry = today + datetime.timedelta(days=7)
    else:
        expiry = today + datetime.timedelta(days=days_ahead)
    
    # Return in YYMMDD format
    return expiry.strftime('%y%m%d')

def get_next_weekly_expiry_full(weekday_target=1) -> str:
    """
    Returns next weekly expiry date in YYYY-MM-DD format for API calls
    
    Args:
        weekday_target: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    
    Returns:
        Expiry date in YYYY-MM-DD format (e.g., '2025-02-06')
    """
    today = get_ist_time()
    days_ahead = (weekday_target - today.weekday()) % 7
    
    if days_ahead == 0:
        if today.hour < 15 or (today.hour == 15 and today.minute < 30):
            expiry = today
        else:
            expiry = today + datetime.timedelta(days=7)
    else:
        expiry = today + datetime.timedelta(days=days_ahead)
    
    return expiry.strftime('%Y-%m-%d')

def get_option_contracts(api: UpstoxAPI, nifty_symbol: str) -> List[Dict]:
    """
    Fetch option contracts from Upstox API matching current weekly expiry (Tuesday)
    Uses robust fallback to fetch all expiries and select the nearest one if needed.
    
    Args:
        api: UpstoxAPI instance
        nifty_symbol: Nifty symbol (e.g., 'NSE_INDEX|Nifty 50')
    
    Returns:
        List of option contracts formatted for strategy use
    """
    try:
        expiry_date = get_next_weekly_expiry_full()  # YYYY-MM-DD format
        encoded_symbol = encode_symbol(nifty_symbol)
        
        url = f"{api.base_url}/option/contract?instrument_key={encoded_symbol}&expiry_date={expiry_date}"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {api.access_token}"
        }
        
        logger.info(f"Fetching option contracts for {expiry_date}...")
        response = requests.get(url, headers=headers, timeout=10)
        
        contracts = []
        if response.status_code == 200:
            data = response.json()
            contracts = data.get('data', [])
            logger.info(f"✓ Fetched {len(contracts)} option contracts for {expiry_date}")
        else:
            logger.error(f"Failed to fetch contracts for precise expiry: {response.status_code} - {response.text[:200]}")
            
        if not contracts:
            logger.warning(f"No contracts for {expiry_date}, fetching all expiries...")
            url2 = f"{api.base_url}/option/contract?instrument_key={encoded_symbol}"
            r2 = requests.get(url2, headers=headers, timeout=10)
            
            if r2.status_code == 200:
                data2 = r2.json()
                all_contracts = data2.get('data') or []
                logger.info(f"Total contracts available: {len(all_contracts)}")
                
                if all_contracts:
                    # Sort expiries using set to remove duplicates
                    expiries = sorted(list(set([c.get('expiry') for c in all_contracts if c.get('expiry')])))
                    if expiries:
                        logger.info(f"Available expiries: {expiries[:5]}")
                        nearest = expiries[0]
                        contracts = [c for c in all_contracts if c.get('expiry') == nearest]
                        logger.info(f"Using nearest expiry: {nearest} ({len(contracts)} contracts)")
            else:
                logger.error(f"All expiries API failed: {r2.status_code} - {r2.text[:200]}")
                
        if not contracts:
            logger.error("No contracts found after all attempts!")
            return []
            
        # The strategy requires these fields, which are already present in v2/option/contract format
        # Filter near ATM if we wanted, but ORB strategy expects full chain and finds ATM later
        return contracts
            
    except Exception as e:
        logger.error(f"Error fetching option contracts: {e}", exc_info=True)
        return []

# ============================================================================
# ORB STRATEGY CLASS
# ============================================================================

class NiftyORBStrategy:
    """Opening Range Breakout Strategy for Nifty 50 Options"""
    
    def __init__(self, api: UpstoxAPI, config: Dict):
        """
        Initialize strategy
        
        Args:
            api: UpstoxAPI instance
            config: Configuration dictionary
        """
        self.api = api
        self.config = config
        
        # Symbols
        self.nifty_symbol = "NSE_INDEX|Nifty 50"
        
        # ORB parameters
        self.orb_minutes = config['ORB_MINUTES']
        self.orb_start = dt.strptime(config['ORB_START_TIME'], '%H:%M').time()
        self.orb_end = dt.strptime(config['ORB_END_TIME'], '%H:%M').time()
        self.orb_buffer = config.get('ORB_BUFFER_POINTS', 10)
        # Validate critical config
        if not config.get('ACCESS_TOKEN'):
            raise ValueError("ACCESS_TOKEN not set in config")
            
        self.lot_size = config['LOT_SIZE']
        self.execute_trades = config['EXECUTE_TRADES']
        
        # Risk Management (New)
        self.max_trades = config.get('MAX_TRADES_PER_DAY', 2)
        self.max_daily_loss = abs(config.get('MAX_DAILY_LOSS', 2000)) # Ensure positive

        # Rs-Based Risk Parameters
        self.profit_target_rs = config.get('PROFIT_TARGET_RS', 1000)
        self.trailing_step_rs = config.get('TRAILING_STEP_RS', 500)
        self.profit_lock_activation_rs = config.get('PROFIT_LOCK_ACTIVATION_RS', 700)
        self.profit_lock_amount_rs = config.get('PROFIT_LOCK_AMOUNT_RS', 200)
        self.initial_sl_rs = config.get('INITIAL_STOP_LOSS_RS', -1000)

        
        # State variables
        self.orb_high = None
        self.orb_low = None
        self.orb_range = None
        self.orb_formed = False
        self.position = None
        self.trade_count = 0
        self.total_pnl = 0.0 # Track daily P&L
        self.trade_completed = False
        self.option_contracts = []  # Store contracts for lookup
        
        # Reporting Config
        self.csv_filename = config.get('CSV_FILENAME', 'trades.csv')
        self.discord_url = config.get('DISCORD_WEBHOOK_URL', '')
        
        self.waiting_for_breakout = True # Needs to be inside range to arm the trigger
        
        logger.info(f"Strategy initialized - {'LIVE TRADING' if self.execute_trades else 'PAPER TRADING'}")

    def log_to_csv(self, trade_data: Dict):
        """Log trade details to CSV file"""
        try:
            file_exists = os.path.isfile(self.csv_filename)
            
            with open(self.csv_filename, mode='a', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=[
                    'Date', 'Symbol', 'Type', 'Strike', 'Entry Time', 'Exit Time', 
                    'Entry Price', 'Exit Price', 'PnL', 'PnL %', 'Exit Reason'
                ])
                
                if not file_exists:
                    writer.writeheader()
                    
                writer.writerow(trade_data)
                logger.info(f"📝 Trade logged to {self.csv_filename}")
                
        except Exception as e:
            logger.error(f"Failed to log to CSV: {e}")

    def send_discord_alert(self, title: str, description: str, color: int):
        """Send embed alert to Discord"""
        if not self.discord_url:
            return
            
        try:
            payload = {
                "embeds": [{
                    "title": title,
                    "description": description,
                    "color": color,
                    "timestamp": dt.now(datetime.UTC).isoformat()
                }]
            }
            
            response = requests.post(self.discord_url, json=payload)
            if response.status_code == 204:
                logger.debug("✓ Discord alert sent")
            else:
                logger.error(f"Failed to send Discord alert: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error sending Discord alert: {e}")
    
    def get_atm_strike(self, spot_price: float) -> int:
        """
        Calculate At-The-Money strike price
        
        Args:
            spot_price: Current Nifty spot price
        
        Returns:
            ATM strike price (rounded to nearest 50)
        """
        return round(spot_price / 50) * 50
    
    def get_option_key(self, strike: int, option_type: str) -> tuple[Optional[str], Optional[str]]:
        """
        Find instrument key and trading symbol from cached contracts
        
        Args:
            strike: Strike price
            option_type: 'CE' or 'PE'
            
        Returns:
            Tuple of (instrument_key, trading_symbol) or (None, None)
        """
        if not self.option_contracts:
            logger.error("Option contracts not loaded")
            return None, None
            
        try:
            for contract in self.option_contracts:
                contract_strike = contract.get('strike_price')
                contract_type = contract.get('instrument_type')
                
                if (contract_strike == float(strike) and contract_type == option_type):
                    key = contract.get('instrument_key')
                    symbol = contract.get('trading_symbol')
                    logger.info(f"✅ {option_type} {strike} -> {symbol}")
                    return key, symbol
            
            logger.error(f"❌ No contract found for Strike: {strike}, Type: {option_type}")
            logger.info(f"Available strikes sample: {[c.get('strike_price') for c in self.option_contracts[:5]]}")
            return None, None
            
        except Exception as e:
            logger.error(f"Error finding option key: {e}")
            return None, None
    
    def calculate_orb_levels(self, candles: List) -> Optional[Dict]:
        """
        Calculate ORB High, Low, Range from 1-minute candles (Aggregation)
        """
        if not candles:
            return None
            
        try:
            # Convert to DataFrame
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Filter for ORB period (9:15 to 9:30)
            # Use the date from the first candle to be safe
            first_ts = df['timestamp'].iloc[0]
            current_date = first_ts.date()
            
            # Get timezone from data if present
            data_tz = first_ts.tzinfo
            
            # Create full datetime objects for start and end
            orb_start_dt = dt.combine(current_date, self.orb_start)
            orb_end_dt = dt.combine(current_date, self.orb_end)
            
            # Make start/end aware if data is aware
            if data_tz:
                orb_start_dt = orb_start_dt.replace(tzinfo=data_tz)
                orb_end_dt = orb_end_dt.replace(tzinfo=data_tz)
            
            # Filter candles: Time >= Start AND Time < End
            mask = (df['timestamp'] >= orb_start_dt) & (df['timestamp'] < orb_end_dt)
            orb_df = df.loc[mask]
            
            if orb_df.empty:
                logger.warning("⚠️ No candles found in ORB period (9:15-9:30)")
                return None
            
            orb_high = orb_df['high'].max()
            orb_low = orb_df['low'].min()
            orb_range = orb_high - orb_low
            
            return {
                'high': orb_high,
                'low': orb_low,
                'range': orb_range
            }
            
        except Exception as e:
            logger.error(f"Error calculating ORB: {e}")
            return None
    

    
    # Indicators Removed (VWAP/Supertrend)
    
    
    def check_breakout(self, current_price: float) -> Optional[str]:
        """
        Check if price has broken out of ORB range
        Logic: Requires price to be inside range (or reset) before triggering
        """
        if not self.orb_formed:
            return None
        
        # Reset Logic: If price is inside the range, we are ready for a new breakout
        if self.orb_low <= current_price <= self.orb_high:
            if not self.waiting_for_breakout:
                logger.info("Values returned to ORB Range - Signal RE-ARMED ⚠️")
                self.waiting_for_breakout = True
            return None

        # Breakout Trigger
        if self.waiting_for_breakout:
            buy_trigger = self.orb_high + self.orb_buffer
            sell_trigger = self.orb_low - self.orb_buffer
            
            # Bullish breakout: Price > ORB High + Buffer
            if current_price > buy_trigger:
                logger.info(f"🚀 BULLISH BREAKOUT CONFIRMED (Price: {current_price} > Trigger: {buy_trigger} [ORB High: {self.orb_high} + {self.orb_buffer} Buffer])")
                self.waiting_for_breakout = False # Consumed
                return 'CE'
            
            # Bearish breakout: Price < ORB Low - Buffer
            elif current_price < sell_trigger:
                logger.info(f"📉 BEARISH BREAKOUT CONFIRMED (Price: {current_price} < Trigger: {sell_trigger} [ORB Low: {self.orb_low} - {self.orb_buffer} Buffer])")
                self.waiting_for_breakout = False # Consumed
                return 'PE'
        
        return None
    
    def enter_position(self, option_type: str, spot_price: float, expiry: str) -> bool:
        """
        Enter a trading position
        
        Args:
            option_type: 'CE' or 'PE'
            spot_price: Current Nifty spot price
            expiry: Option expiry date
        
        Returns:
            True if position entered successfully, False otherwise
        """
        try:
            # Calculate ATM strike
            strike = self.get_atm_strike(spot_price)
            
            # Get option instrument key and trading symbol from contracts
            instrument_key, trading_symbol = self.get_option_key(strike, option_type)
            if not instrument_key or not trading_symbol:
                return False
            
            # Get option quote using trading symbol (Upstox API uses trading_symbol as key)
            quote = self.api.get_quote(instrument_key)
            if not quote:
                logger.error(f"Failed to get quote for {instrument_key}")
                return False
            
            option_price = quote.get('last_price', 0)
            if option_price == 0:
                logger.error("Invalid option price received")
                return False
            
            # Calculate levels (Rs Based)
            entry_price = option_price
            
            # 2. Set Final Levels
            sl_points = abs(self.initial_sl_rs) / self.lot_size
            stop_loss = entry_price - sl_points
            
            # No fixed target price because we trail
            target = float('inf')
            
            # Create position object
            self.position = {
                'symbol': instrument_key,
                'trading_symbol': trading_symbol,
                'option_type': option_type,
                'strike': strike,
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'target': target,
                'max_price': entry_price, # Track High for Trailing SL
                'entry_time': get_ist_time(),
                'spot_price': spot_price,
                'quantity': self.lot_size,
                'sl_order_id': None  # Track real order id in Exchange
            }
            
            # Log entry details
            logger.info("\n" + "="*70)
            logger.info("🎯 POSITION ENTRY")
            logger.info("="*70)
            logger.info(f"Symbol:      {trading_symbol}")
            logger.info(f"Instrument:  {instrument_key}")
            logger.info(f"Type:        {option_type} ({'CALL' if option_type == 'CE' else 'PUT'})")
            logger.info(f"Strike:      {strike}")
            logger.info(f"Spot Price:  {spot_price}")
            logger.info(f"Entry Price: ₹{entry_price:.2f}")
            logger.info(f"Target Mode: Trailing every ₹{self.trailing_step_rs} after ₹{self.profit_target_rs}")
            logger.info(f"Stop Loss:   ₹{stop_loss:.2f} (₹{self.initial_sl_rs})")
            logger.info(f"Exit Condition: TRAILING SL 🛑")
            logger.info(f"Quantity:    {self.lot_size} lots")
            logger.info(f"Entry Time:  {self.position['entry_time'].strftime('%H:%M:%S')}")
            logger.info("="*70 + "\n")
            
            # Place order (Live or Sandbox)
            # Use real API if execute trades is true or if we are configured to use Sandbox
            if self.execute_trades or getattr(self.api, 'use_sandbox', False):
                order = self.api.place_order(
                    symbol=instrument_key,
                    quantity=self.lot_size,
                    transaction_type='BUY',
                    order_type='MARKET',
                    product='I'
                )
                
                if order:
                    # Sandbox sometimes returns order_ref_id instead of order_id
                    order_data = order.get('data', {})
                    self.position['order_id'] = order_data.get('order_id') or order_data.get('order_ref_id')
                    logger.info(f"✓ {'Live' if self.execute_trades else 'Sandbox'} Entry Order executed: {order}")
                    
                    # IMMEDIATELY PLACE SL ORDER IN EXCHANGE
                    if self.execute_trades or getattr(self.api, 'use_sandbox', False):
                        sl_order = self.api.place_order(
                            symbol=instrument_key,
                            quantity=self.lot_size,
                            transaction_type='SELL',
                            order_type='SL',  # Stop Loss Limit Option
                            product='I',
                            price=round(stop_loss - 0.5, 2),
                            trigger_price=round(stop_loss, 2)
                        )
                        
                        if sl_order:
                            # Extract the actual payload dictionary, modify requests need it
                            sl_order_data = sl_order.get('data', {})
                            self.position['sl_order_id'] = sl_order_data.get('order_id') or sl_order_data.get('order_ref_id')
                            logger.info(f"✓ {'Live' if self.execute_trades else 'Sandbox'} SL Order initialized at exchange at ₹{stop_loss:.2f}")
                            
                            # Set actual trigger params locally:
                            # Required by many exchanges: Limit needs to be slightly lower than Trigger for SELL SL
                            payload_for_sl = {
                                'order_id': self.position['sl_order_id'],
                                'new_trigger_price': round(stop_loss, 2),
                                'new_price': round(stop_loss - 0.5, 2)
                            }
                            
                            self.api.modify_order(**payload_for_sl)
                            
                        else:
                            logger.error("✗ Failed to execute safety SL order in Upstox! Closing manually...")
                            # If SL fails, immediately exit the live/sandbox trade as a safety measure
                            self.api.place_order(symbol=instrument_key, quantity=self.lot_size, transaction_type='SELL', order_type='MARKET')
                            self.position = None
                            return False
                    else:
                        self.position['sl_order_id'] = None
                        logger.info(f"✓ Sandbox SL Local tracking initialized at ₹{stop_loss:.2f}")

                else:
                    logger.error("✗ Failed to execute entry order")
                    self.position = None
                    return False
            else:
                self.position['order_id'] = f"mock_{int(time.time())}"
                self.position['sl_order_id'] = f"mock_sl_{int(time.time())}"
                logger.info(f"📝 PAPER TRADE - Mock Order ID: {self.position['order_id']}")
            self.trade_count += 1
            
            # Send Discord Alert (Entry)
            discord_desc = (
                f"**Strike:** {strike} {option_type}\n"
                f"**Price:** ₹{entry_price:.2f}\n"
                f"**Spot:** {spot_price}\n"
                f"**Stop Loss:** ₹{self.initial_sl_rs} Rs"
            )
            self.send_discord_alert("🚀 TRADE ENTRY", discord_desc, 3447003) # Blue
            
            return True
            
        except Exception as e:
            logger.error(f"Error entering position: {e}")
            return False
    
    def monitor_position(self) -> Optional[str]:
        """
        Monitor active position for exit conditions
        Checks every 1 second
        """
        if not self.position:
            return None
        
        try:
            symbol = self.position['symbol']
            quote = self.api.get_quote(symbol)
            
            if not quote:
                logger.warning("Failed to get quote for position monitoring")
                return None
            
            current_price = quote.get('last_price', 0)
            entry_price = self.position['entry_price']
            
            # Update High Water Mark
            if current_price > self.position['max_price']:
                self.position['max_price'] = current_price
                
            # Rs-Based Risk Management
            max_pnl_rs = (self.position['max_price'] - entry_price) * self.lot_size
            current_pnl_rs = (current_price - entry_price) * self.lot_size
            
            calculated_sl = self.position['stop_loss']
            tier_hit = False
            lock_msg = ""
            
            # 1. Trailing every 500 after reaching 1000
            if max_pnl_rs >= self.profit_target_rs:
                # Continuous trailing 500 Rs behind the max price
                locked_profit_rs = max_pnl_rs - self.trailing_step_rs
                calculated_sl = entry_price + (locked_profit_rs / self.lot_size)
                tier_hit = True
                lock_msg = "[TRAILING 📈]"
                
            # 2. Lock 200 if it reaches 700
            elif max_pnl_rs >= self.profit_lock_activation_rs:
                locked_profit_rs = self.profit_lock_amount_rs
                calculated_sl = entry_price + (locked_profit_rs / self.lot_size)
                tier_hit = True
                lock_msg = "[PROFIT LOCKED 🔒]"
                
                # Update SL only if it moves UP (Never move SL down)
            if calculated_sl > self.position['stop_loss']:
                old_sl = self.position['stop_loss']
                new_sl = round(calculated_sl, 2)
                self.position['stop_loss'] = new_sl
                logger.info(f"⚡ TRAILING SL UPDATED: ₹{old_sl:.2f} -> ₹{new_sl:.2f} (Max PnL: ₹{max_pnl_rs:.2f}) {lock_msg}")
                
                # Update Actual SL Order in Exchange
                if (self.execute_trades or getattr(self.api, 'use_sandbox', False)) and self.position.get('sl_order_id'):
                    # Limit price is 50 paise lower to guarantee execution on sharp drops
                    self.api.modify_order(
                        order_id=self.position['sl_order_id'], 
                        new_trigger_price=new_sl, 
                        new_price=round(new_sl - 0.5, 2)
                    )

            pnl_percent = (current_price - entry_price) / entry_price
            
            logger.info(f"  Price: ₹{current_price:.2f} | SL: ₹{self.position['stop_loss']:.2f} | PnL: ₹{current_pnl_rs:.2f} ({pnl_percent*100:+.2f}%)")
            
            # Target check is removed because exit is handled fully by trailing SL
            
            # 2. Check Stop Loss (Trailing or Initial)
            if current_price <= self.position['stop_loss']:
                logger.warning(f"🛑 STOP LOSS/TRAILING SL HIT at ₹{current_price:.2f} (PnL: ₹{current_pnl_rs:.2f})")
                return 'STOP_LOSS'
            
            return None
            
        except Exception as e:
            logger.error(f"Error monitoring position: {e}")
            return None
    
    def exit_position(self, exit_reason: str):
        """
        Exit current position
        
        Args:
            exit_reason: Reason for exit (STOP_LOSS, TARGET, etc.)
        """
        if not self.position:
            return
        
        try:
            exit_time = get_ist_time()
            
            # Get final price
            quote = self.api.get_quote(self.position['symbol'])
            exit_price = quote.get('last_price', 0) if quote else 0
            
            # Calculate final P&L
            pnl = exit_price - self.position['entry_price']
            pnl_percent = (pnl / self.position['entry_price']) * 100
            
            logger.info("\n" + "="*70)
            logger.info("🚪 POSITION EXIT")
            logger.info("="*70)
            logger.info(f"Exit Reason: {exit_reason}")
            logger.info(f"Entry:       ₹{self.position['entry_price']:.2f}")
            logger.info(f"Exit:        ₹{exit_price:.2f}")
            logger.info(f"P&L:         ₹{pnl:.2f} ({pnl_percent:+.2f}%)")
            logger.info(f"Duration:    {(exit_time - self.position['entry_time']).total_seconds() / 60:.1f} minutes")
            logger.info("="*70 + "\n")
            
            # Place sell order if live trading (MANUAL EXITS OR PAPER TRACKING)
            # If the Stop loss trigger directly hit, Upstox fired it. Only actively close here if it hasn't fired.
            if (self.execute_trades or getattr(self.api, 'use_sandbox', False)) and exit_reason != 'STOP_LOSS':
                order = self.api.place_order(
                    symbol=self.position['symbol'],
                    quantity=self.lot_size,
                    transaction_type='SELL',
                    order_type='MARKET',
                    product='I'
                )
                
                if order:
                    logger.info(f"✓ Exit order executed: {order}")
                else:
                    logger.error("✗ Failed to execute manual exit order")
                    
            elif (self.execute_trades or getattr(self.api, 'use_sandbox', False)) and exit_reason == 'STOP_LOSS':
                logger.info("✓ Trusting Exchange SL trigger executed our order.")
            
            # Log to CSV
            trade_record = {
                'Date': exit_time.strftime('%Y-%m-%d'),
                'Symbol': self.position['trading_symbol'],
                'Type': self.position['option_type'],
                'Strike': self.position['strike'],
                'Entry Time': self.position['entry_time'].strftime('%H:%M:%S'),
                'Exit Time': exit_time.strftime('%H:%M:%S'),
                'Entry Price': f"{self.position['entry_price']:.2f}",
                'Exit Price': f"{exit_price:.2f}",
                'PnL': f"{pnl:.2f}",
                'PnL %': f"{pnl_percent:.2f}%",
                'Exit Reason': exit_reason
            }
            self.log_to_csv(trade_record)
            
            # Send Discord Alert (Exit)
            is_profit = pnl > 0
            color = 5763719 if is_profit else 15548997 # Green / Red
            
            discord_desc = (
                f"**Strike:** {self.position['strike']} {self.position['option_type']}\n"
                f"**P&L:** ₹{pnl:.2f} ({pnl_percent:.2f}%)\n"
                f"**Exit Price:** ₹{exit_price:.2f}\n"
                f"**Reason:** {exit_reason}"
            )
            title = "💰 PROFIT BOOKED" if is_profit else "🛑 STOP LOSS HIT"
            self.send_discord_alert(title, discord_desc, color)
            
            # Clear position
            self.position = None
            
            # Update Total P&L
            self.total_pnl += pnl
            logger.info(f"💰 CUMULATIVE DAILY P&L: ₹{self.total_pnl:.2f}")

            if self.trade_count >= self.max_trades:
                logger.info(f"📅 Reached max trades for the day ({self.max_trades}).")
                self.trade_completed = True
                logger.info("Exiting bot completely for the day. 🛑")
                sys.exit(0)
            elif self.total_pnl <= -self.max_daily_loss:
                logger.warning(f"� Max daily loss hit (₹{-self.max_daily_loss}). Exiting bot completely for safety. 🛑")
                self.trade_completed = True
                sys.exit(0)
            
        except Exception as e:
            logger.error(f"Error exiting position: {e}")
    
    def run(self, expiry_date: str):
        """
        Main strategy execution loop
        
        Args:
            expiry_date: Option expiry in YYMMDD format
        """
        logger.info("\n" + "="*80)
        logger.info("🚀 NIFTY 50 ORB STRATEGY - STARTED")
        logger.info("="*80)
        logger.info(f"Expiry Date:      {expiry_date}")
        logger.info(f"ORB Period:       {self.config['ORB_START_TIME']} - {self.config['ORB_END_TIME']}")
        logger.info(f"Risk Mode:        Rs Based (Trail/Lock: {self.profit_target_rs}/{self.trailing_step_rs} & {self.profit_lock_activation_rs}/{self.profit_lock_amount_rs})")
        logger.info(f"Lot Size:         {self.lot_size}")
        logger.info(f"Execution Mode:   {'🔴 LIVE TRADING' if self.execute_trades else '📝 PAPER TRADING'}")
        logger.info("="*80 + "\n")
        
        # Load Option Contracts
        logger.info("📥 Loading option contracts (Using Live Token)...")
        # We pass access_token string to force the live connection in get_option_contracts
        self.option_contracts = get_option_contracts(self.api, self.nifty_symbol)
        if not self.option_contracts:
            logger.error("❌ Failed to load option contracts! Strategy cannot run.")
            return
        
        logger.info(f"✓ Ready with {len(self.option_contracts)} contracts")
        
        try:
            while True:
                now = get_ist_time()
                current_time = now.time()
                
                # ============================================================
                # STAGE 1: OPENING RANGE FORMATION
                # ============================================================
                if self.orb_start <= current_time <= self.orb_end and not self.orb_formed:
                    quote = self.api.get_quote(self.nifty_symbol)
                    if quote:
                        ltp = quote.get('last_price', 0)
                        logger.info(f"⏱️  Forming ORB... Nifty: {ltp:.2f}")
                    
                    time.sleep(5)  # Check every 5 seconds during ORB formation
                
                # ============================================================
                # STAGE 2: CALCULATE ORB LEVELS
                # ============================================================
                elif current_time > self.orb_end and not self.orb_formed:
                    logger.info("📊 Calculating ORB levels...")
                    
                    # Fetch 1-minute candles for ORB period (Aggregation)
                    candles = self.api.get_intraday_candles(
                        symbol=self.nifty_symbol,
                        unit='minutes',
                        interval=1
                    )
                    
                    if candles:
                        orb_data = self.calculate_orb_levels(candles)
                        
                        if orb_data:
                            self.orb_high = orb_data['high']
                            self.orb_low = orb_data['low']
                            self.orb_range = orb_data['range']
                            self.orb_formed = True
                            
                            logger.info("\n" + "="*70)
                            logger.info("✅ ORB LEVELS FORMED")
                            logger.info("="*70)
                            logger.info(f"High:  {self.orb_high:.2f}")
                            logger.info(f"Low:   {self.orb_low:.2f}")
                            logger.info(f"Range: {self.orb_range:.2f} ({(self.orb_range/self.orb_low)*100:.2f}%)")
                            logger.info("="*70 + "\n")
                    else:
                        logger.warning("No candles received, retrying...")
                    
                    time.sleep(5)
                
                # ============================================================
                # STAGE 3: MONITOR FOR BREAKOUT
                # ============================================================
                elif self.orb_formed and not self.position and not self.trade_completed:
                    quote_data = self.api.get_quote(self.nifty_symbol)
                    
                    if quote_data:
                        spot_price = quote_data.get('last_price', 0)
                        
                        breakout = self.check_breakout(spot_price)
                        
                        if breakout:
                            # Breakout confirmed - enter position
                            success = self.enter_position(breakout, spot_price, expiry_date)
                            if not success:
                                logger.error("Failed to enter position, continuing to monitor...")
                        else:
                            logger.info(f"⏳ Price: {spot_price:.2f} | Range: {self.orb_low:.2f}-{self.orb_high:.2f}")
                    
                    time.sleep(1)  # Check every 1 second
                
                # ============================================================
                # STAGE 4: MONITOR POSITION
                # ============================================================
                elif self.position:
                    exit_signal = self.monitor_position()
                    
                    if exit_signal:
                        self.exit_position(exit_signal)
                        
                        # Stop after one trade
                        logger.info("Trade completed. Waiting for market close...")
                    
                    time.sleep(1)  # Monitor every 1 second
                
                # ============================================================
                # MARKET CLOSE CHECK
                # ============================================================
                market_close = dt.strptime("15:15", "%H:%M").time()
                if current_time >= market_close:
                    logger.info("\n" + "="*70)
                    logger.info("🔔 Market Closed")
                    logger.info("="*70)
                    
                    # Exit any open position at market close
                    if self.position:
                        logger.warning("Closing position at market close")
                        self.exit_position("MARKET_CLOSE")
                    
                    break
                
                # Small sleep to avoid excessive API calls
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("\n⚠️  Strategy stopped by user (Ctrl+C)")
            if self.position:
                logger.warning("Open position exists. Consider manual exit.")
        
        except Exception as e:
            logger.error(f"❌ Strategy error: {e}", exc_info=True)
        
        finally:
            logger.info("\n" + "="*80)
            logger.info("🏁 STRATEGY EXECUTION COMPLETED")
            logger.info("="*80)
            logger.info(f"Total Trades: {self.trade_count}")
            logger.info("="*80 + "\n")



# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main entry point"""
    
    # Validate configuration
    if CONFIG['ACCESS_TOKEN'] == 'EY....(YOUR LIVE TOKEN)....':
        logger.error("❌ Please set your Upstox LIVE access_token in CONFIG")
        return
        
    use_sandbox = CONFIG.get('USE_SANDBOX_API', False)
    if use_sandbox and (not CONFIG.get('SANDBOX_TOKEN') or CONFIG['SANDBOX_TOKEN'] == 'EY....(YOUR SANDBOX TOKEN)....'):
        logger.warning("⚠️ USE_SANDBOX_API is true but SANDBOX_TOKEN is missing. Orders will fail in Sandbox.")
    
    # Auto-calculate Tuesday expiry for Nifty weekly options
    expiry_date = get_next_weekly_expiry()  # YYMMDD format
    expiry_full = get_next_weekly_expiry_full()  # YYYY-MM-DD format
    logger.info(f"📅 Auto-calculated Nifty weekly expiry (Tuesday): {expiry_full} ({expiry_date})")
    
    # Initialize API
    try:
        api = UpstoxAPI(
            access_token=CONFIG['ACCESS_TOKEN'], 
            sandbox_token=CONFIG.get('SANDBOX_TOKEN', ''),
            use_sandbox=use_sandbox
        )
        
        # Test API connection
        logger.info("Testing API connection...")
        test_quote = api.get_quote("NSE_INDEX|Nifty 50")
        
        if test_quote:
            logger.info(f"✓ API connected. Nifty: {test_quote.get('last_price', 0)}")
        else:
            logger.error("❌ Failed to connect to Upstox API. Check your token.")
            logger.error("💡 Possible reasons:")
            logger.error("   1. Access token has expired (tokens typically expire daily)")
            logger.error("   2. Invalid or incorrect token format")
            logger.error("   3. Network connectivity issues")
            logger.error("   4. Market is closed (API may not return data)")
            return
        
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize API: {e}")
        return
    
    # Initialize and run strategy
    try:
        strategy = NiftyORBStrategy(api, CONFIG)
        strategy.run(expiry_date=expiry_date)
        
    except Exception as e:
        logger.error(f"❌ Strategy execution failed: {e}", exc_info=True)


if __name__ == "__main__":
    print("\n" + "="*80)
    print("  NIFTY 50 OPTIONS ORB STRATEGY")
    print("  Using Upstox API for Live Data")
    print("="*80)
    print("\n⚠️  IMPORTANT REMINDERS:")
    print("  1. Set your ACCESS_TOKEN in CONFIG section")
    print("  2. Expiry auto-calculated for Tuesday (Nifty weekly expiry)")
    print("  3. Verify LOT_SIZE is current (default: 25)")
    print("  4. EXECUTE_TRADES is False by default (paper trading)")
    print("  5. Set USE_SANDBOX_API=True if you want to use the Upstox Sandbox for API calls")
    print("  6. Set EXECUTE_TRADES=True only when ready for live trading")
    print("\n" + "="*80 + "\n")
    
    # Confirmation for live trading
    if CONFIG['EXECUTE_TRADES']:
        print("⚠️  ⚠️  ⚠️  LIVE TRADING MODE ENABLED ⚠️  ⚠️  ⚠️")
        response = input("Are you sure you want to execute real trades? (yes/no): ")
        if response.lower() != 'yes':
            print("Exiting for safety. Set EXECUTE_TRADES=False for paper trading.")
            exit()
    
    main()