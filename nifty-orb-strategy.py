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
    'ACCESS_TOKEN': 'eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI1NUJBOVgiLCJqdGkiOiI2OThlOWU3N2UyNGM4NDExZmY2NTY0YWYiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc3MDk1NDM1OSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzcxMDIwMDAwfQ.kWNvVW58esFcFD_Xha2wdJynYtSzkgxtxyrfLAnaRs8',
    
    # Trading Parameters
    # EXPIRY_DATE auto-calculated for Tuesday (Nifty weekly expiry)
    'LOT_SIZE': 65,           # Nifty option lot size (verify current size)
    
    # ORB Parameters
    'ORB_MINUTES': 15,        # Opening range duration in minutes
    'ORB_START_TIME': '09:15',
    'ORB_END_TIME': '09:30',
    
    # Risk Management
    # SL/Target are now purely ATR based
    
    # ATR Risk Management
    'ATR_PERIOD': 14,
    'ATR_MULTIPLIER_SL': 0.5,    # Tighter SL for Intraday (approx 75-100 pts)
    'ATR_MULTIPLIER_TARGET': 1.0, # Realistic Intraday Target (approx 150-200 pts)
    'OPTION_DELTA': 0.5,      # Approximation for ATM delta

    
    # -------------------------------------------------------------------------
    # IMPROVED RISK MANAGEMENT
    # -------------------------------------------------------------------------
    'MAX_TRADES_PER_DAY': 2,    # Stop after 2 trades (Win or Loss)
    'MAX_DAILY_LOSS': 2000,     # Stop trading if cumulative loss exceeds ₹2000
    'TRAILING_START_PERCENT': 0.05, # Only start trailing SL after 5% profit
    # -------------------------------------------------------------------------
    
    # Execution
    'EXECUTE_TRADES': False,   # Set to True for live trading, False for paper trading
    
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
    
    def __init__(self, access_token: str):
        """
        Initialize Upstox API client
        
        Args:
            access_token: Upstox API access token
        """
        self.access_token = access_token
        self.base_url = "https://api.upstox.com/v2"
        self.headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }
        logger.info("Upstox API initialized")
    
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
            url = f"https://api.upstox.com/v2/historical-candle/intraday/{encoded_symbol}/{interval_str}"
            
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
            url = f"https://api.upstox.com/v2/historical-candle/{encoded_symbol}/{interval}/{to_date}/{from_date}"
            
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
                   product: str = 'I') -> Optional[Dict]:
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
            url = f"{self.base_url}/order/place"
            
            payload = {
                'quantity': quantity,
                'product': product,
                'validity': 'DAY',
                'price': 0,
                'tag': 'ORB_Strategy',
                'instrument_token': symbol,
                'order_type': order_type,
                'transaction_type': transaction_type,
                'disclosed_quantity': 0,
                'trigger_price': 0,
                'is_amo': False
            }
            
            logger.info(f"Placing {transaction_type} order for {symbol}")
            
            response = requests.post(
                url, 
                headers=self.headers, 
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
    
    def get_positions(self) -> Optional[Dict]:
        """Get current positions"""
        try:
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

def get_option_contracts(access_token: str, nifty_symbol: str) -> List[Dict]:
    """
    Fetch option contracts from Upstox API for current weekly expiry
    
    Args:
        access_token: Upstox API access token
        nifty_symbol: Nifty symbol (e.g., 'NSE_INDEX|Nifty 50')
    
    Returns:
        List of option contracts
    """
    try:
        expiry_date = get_next_weekly_expiry_full()  # YYYY-MM-DD format
        encoded_symbol = encode_symbol(nifty_symbol)
        
        url = f"https://api.upstox.com/v2/option/contract?instrument_key={encoded_symbol}&expiry_date={expiry_date}"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        
        logger.info(f"Fetching option contracts for expiry: {expiry_date}")
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            contracts = data.get('data', [])
            logger.info(f"✓ Fetched {len(contracts)} option contracts")
            return contracts
        else:
            logger.error(f"Failed to fetch contracts: {response.status_code}")
            return []
            
    except Exception as e:
        logger.error(f"Error fetching option contracts: {e}")
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
        # Validate critical config
        if not config.get('ACCESS_TOKEN'):
            raise ValueError("ACCESS_TOKEN not set in config")
            
        self.lot_size = config['LOT_SIZE']
        self.execute_trades = config['EXECUTE_TRADES']
        
        # Risk Management (New)
        self.max_trades = config.get('MAX_TRADES_PER_DAY', 2)
        self.max_daily_loss = abs(config.get('MAX_DAILY_LOSS', 2000)) # Ensure positive
        self.trailing_start_percent = config.get('TRAILING_START_PERCENT', 0.05)

        # ATR Parameters
        self.atr_period = config.get('ATR_PERIOD', 14)
        self.atr_multiplier_sl = config.get('ATR_MULTIPLIER_SL', 1.5)
        self.atr_multiplier_target = config.get('ATR_MULTIPLIER_TARGET', 3.0)
        self.option_delta = config.get('OPTION_DELTA', 0.5)

        
        # State variables
        self.orb_high = None
        self.orb_low = None
        self.orb_range = None
        self.orb_formed = False
        self.position = None
        self.trade_count = 0
        self.total_pnl = 0.0 # Track daily P&L
        self.trade_completed = False
        self.trade_completed = False
        self.option_contracts = []  # Store contracts for lookup
        self.daily_atr = None       # Store calculated Daily ATR
        
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
                    "timestamp": dt.utcnow().isoformat()
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
    
    def calculate_atr(self, candles: List, period: int = 14) -> Optional[float]:
        """
        Calculate Average True Range (ATR) using Wilder's Smoothing
        """
        if not candles or len(candles) < period + 1:
            logger.warning(f"Not enough candles for ATR (Need {period+1}, Got {len(candles) if candles else 0})")
            return None
            
        try:
            # Upstox returns list of lists: [timestamp, open, high, low, close, volume, oi]
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
            
            # Explicitly sort by timestamp ascending
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.sort_values('timestamp', inplace=True)
            df.reset_index(drop=True, inplace=True)
            
            # Ensure columns exist (redundant now but good for safety if format changes)
            required_cols = ['high', 'low', 'close']
            if not all(col in df.columns for col in required_cols):
                logger.error("Candle data missing required columns")
                return None
            
            # Helper for True Range
            df['high_low'] = df['high'] - df['low']
            df['high_close'] = (df['high'] - df['close'].shift(1)).abs()
            df['low_close'] = (df['low'] - df['close'].shift(1)).abs()
            
            df['tr'] = df[['high_low', 'high_close', 'low_close']].max(axis=1)
            
            # Wilder's Smoothing (RMA)
            # First value is SMA of TR
            # Subsequent values: ((Previous ATR * (period - 1)) + Current TR) / period
            
            # Pandas ewm adjustment for Wilder's: alpha = 1/period
            atr = df['tr'].ewm(alpha=1/period, min_periods=period, adjust=False).mean()
            
            current_atr = atr.iloc[-1]
            logger.info(f"📊 Calculated ATR ({period}): {current_atr:.2f}")
            return current_atr
            
        except Exception as e:
            logger.error(f"Error calculating ATR: {e}")
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
        if self.orb_low < current_price < self.orb_high:
            if not self.waiting_for_breakout:
                logger.info("Values returned to ORB Range - Signal RE-ARMED ⚠️")
                self.waiting_for_breakout = True
            return None

        # Breakout Trigger
        if self.waiting_for_breakout:
            # Bullish breakout: Price > ORB High
            if current_price > self.orb_high:
                logger.info(f"🚀 BULLISH BREAKOUT CONFIRMED (Price: {current_price} > ORB High: {self.orb_high})")
                self.waiting_for_breakout = False # Consumed
                return 'CE'
            
            # Bearish breakout: Price < ORB Low
            elif current_price < self.orb_low:
                logger.info(f"📉 BEARISH BREAKOUT CONFIRMED (Price: {current_price} < ORB Low: {self.orb_low})")
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
            # 0. Update ATR dynamically before entry
            self.update_atr()

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
            
            # Calculate levels (Dynamic with ATR or Fixed %)
            entry_price = option_price
            
            
            # ATR Based Risk Management
            if self.daily_atr:
                # Option Volatility Estimate = Nifty ATR * Delta
                # Delta is typically 0.5 for ATM options
                option_volatility = self.daily_atr * self.option_delta
                
                sl_dist = option_volatility * self.atr_multiplier_sl
                target_dist = option_volatility * self.atr_multiplier_target
                
                logger.info(f"📊 Using ATR Based Risk Management (ATR: {self.daily_atr:.2f})")
                logger.info(f"   Option Volatility Est: {option_volatility:.2f} (Delta: {self.option_delta})")
                logger.info(f"   ATR SL Dist: {sl_dist:.2f} (x{self.atr_multiplier_sl})")
                logger.info(f"   ATR Target Dist: {target_dist:.2f} (x{self.atr_multiplier_target})")
                
                
            else:
                # ATR IS MANDATORY NOW
                logger.error("❌ ATR not available. Cannot calculate Risk Management. Entry Aborted.")
                return False
            
            # 2. Set Final Levels (Pure ATR)
            stop_loss = entry_price - sl_dist
            target = entry_price + target_dist
            
            # Create position object
            self.position = {
                'symbol': instrument_key,
                'trading_symbol': trading_symbol,
                'option_type': option_type,
                'strike': strike,
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'stop_loss': stop_loss,
                'target': target,
                'atr_sl_dist': sl_dist, # Store for Trailing SL

                'max_price': entry_price, # Track High for Trailing SL
                'entry_time': get_ist_time(),
                'spot_price': spot_price,
                'quantity': self.lot_size
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
            logger.info(f"Target:      ₹{target:.2f} (+{target_dist:.2f} pts)")
            logger.info(f"Stop Loss:   ₹{stop_loss:.2f} (-{sl_dist:.2f} pts)")
            logger.info(f"Exit Condition: TARGET 🎯 OR TRAILING SL 🛑")
            logger.info(f"Quantity:    {self.lot_size} lots")
            logger.info(f"Entry Time:  {self.position['entry_time'].strftime('%H:%M:%S')}")
            logger.info("="*70 + "\n")
            
            # Place order if live trading
            if self.execute_trades:
                order = self.api.place_order(
                    symbol=instrument_key,
                    quantity=self.lot_size,
                    transaction_type='BUY',
                    order_type='MARKET',
                    product='I'
                )
                
                if order:
                    self.position['order_id'] = order.get('order_id')
                    logger.info(f"✓ Live order executed: {order}")
                else:
                    logger.error("✗ Failed to execute order")
                    self.position = None
                    return False
            else:
                logger.info("📝 PAPER TRADE - No real order placed")
            
            self.trade_count += 1
            
            # Send Discord Alert (Entry)
            discord_desc = (
                f"**Strike:** {strike} {option_type}\n"
                f"**Price:** ₹{entry_price:.2f}\n"
                f"**Spot:** {spot_price}\n"
                f"**Stop Loss:** -{sl_dist:.2f} pts (ATR)"
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
                
            # Calculate Dynamic Trailing SL
            # ---------------------------------------------------------------------
            # RISK UPGRADE: Only trail if we are in significant profit
            # ---------------------------------------------------------------------
            trailing_activation_price = entry_price * (1 + self.trailing_start_percent)
            
            if self.position['max_price'] >= trailing_activation_price:
                # 1. Standard ATR Trailing
                # SL is ATR Distance below the Max Price reached
                atr_trailing_sl = self.position['max_price'] - self.position['atr_sl_dist']
                
                # 2. Profit Locking Tiers (Secure Gains)
                # Calculate max profit percentage reached
                max_pnl_percent = (self.position['max_price'] - entry_price) / entry_price
                
                profit_lock_sl = 0.0
                tier_hit = False
                
                # Tier 2: 20% Profit -> Lock 15% (Aggressive)
                if max_pnl_percent >= 0.20:
                    profit_lock_sl = entry_price * 1.15
                    tier_hit = True
                # Tier 1: 8% Profit -> Lock 5% (Conservative)
                elif max_pnl_percent >= 0.08:
                    profit_lock_sl = entry_price * 1.05
                    tier_hit = True
                
                # 3. Combine: Take the HIGHER of ATR Trailing or Profit Lock
                calculated_sl = max(atr_trailing_sl, profit_lock_sl)
                
                # --------------------------------------------------------
                # BREAKEVEN LOGIC: If profit > 5%, ensure SL >= Entry Price
                # --------------------------------------------------------
                if not tier_hit:
                    # Only apply simple breakeven if no higher tier was hit
                    calculated_sl = max(calculated_sl, entry_price)
                
                # Update SL only if it moves UP (Never move SL down)
                if calculated_sl > self.position['stop_loss']:
                    old_sl = self.position['stop_loss']
                    self.position['stop_loss'] = calculated_sl
                    
                    log_msg = f"⚡ TRAILING SL UPDATED: ₹{old_sl:.2f} -> ₹{calculated_sl:.2f} (Max: ₹{self.position['max_price']:.2f})"
                    if tier_hit:
                        log_msg += f" [PROFIT LOCKED 🔒]"
                    logger.info(log_msg)

            # Calculate P&L
            pnl = current_price - entry_price
            pnl_percent = (pnl / entry_price)
            
            logger.info(f"  Price: ₹{current_price:.2f} | SL: ₹{self.position['stop_loss']:.2f} | P&L: {pnl_percent*100:+.2f}%")
            
            # 1. Check Target
            if current_price >= self.position['target']:
                 logger.info(f"🎯 TARGET HIT at ₹{current_price:.2f}")
                 return 'TARGET_HIT'

            # 2. Check Stop Loss (Trailing)
            if current_price <= self.position['stop_loss']:
                logger.warning(f"🛑 STOP LOSS HIT at ₹{current_price:.2f}")
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
            
            # Place sell order if live trading
            if self.execute_trades:
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
                    logger.error("✗ Failed to execute exit order")
            
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

            # Check Daily Loss Limit
            if self.total_pnl <= -self.max_daily_loss:
                self.trade_completed = True
                logger.warning(f"🛑 MAX DAILY LOSS HIT (₹{self.total_pnl:.2f}) - Stopping for the day")
                return

            # Check Max Trades Limit
            if self.trade_count >= self.max_trades:
                self.trade_completed = True
                logger.warning(f"🛑 MAX TRADES LIMIT REACHED ({self.trade_count}) - Stopping for the day")
                return
            
            # Logic: Stop if Target Hit, Continue if SL Hit
            if exit_reason == 'TARGET_HIT':
                self.trade_completed = True
                logger.info("📅 Daily Target Achieved - Stopping for the day 🏆")
            elif exit_reason == 'STOP_LOSS':
                self.trade_completed = False
                logger.info("🔄 Stop Loss Hit - Resuming monitoring for re-entry...")
                # Note: waiting_for_breakout will be set to True automatically 
                # when price returns to range in check_breakout
            else:
                # For Manual/Market Close exits, stop
                self.trade_completed = True
            
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
        logger.info(f"Risk Mode:        Pure ATR (SL x{self.atr_multiplier_sl}, Target x{self.atr_multiplier_target})")
        logger.info(f"Lot Size:         {self.lot_size}")
        logger.info(f"Execution Mode:   {'🔴 LIVE TRADING' if self.execute_trades else '📝 PAPER TRADING'}")
        logger.info("="*80 + "\n")
        
        # Load Option Contracts
        logger.info("📥 Loading option contracts...")
        self.option_contracts = get_option_contracts(self.api.access_token, self.nifty_symbol)
        if not self.option_contracts:
            logger.error("❌ Failed to load option contracts! Strategy cannot run.")
            return
        
        logger.info(f"✓ Ready with {len(self.option_contracts)} contracts")
        
        # Calculate Daily ATR
        # Calculate Daily ATR
        self.update_atr()
        
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
            logger.info(f"Total Trades: {self.trade_count}")
            logger.info("="*80 + "\n")

    def update_atr(self):
        """
        Fetch historical + intraday data and calculate dynamic 5-minute ATR
        """
        logger.info("📊 Updating ATR with latest market data...")
        try:
            # 1. Fetch Historical Data (Last 5 days, excluding today)
            to_date = dt.now().strftime('%Y-%m-%d')
            from_date = (dt.now() - timedelta(days=5)).strftime('%Y-%m-%d')
            
            historical_candles = self.api.get_historical_candles(
                symbol=self.nifty_symbol,
                interval='1minute',
                from_date=from_date,
                to_date=to_date
            ) or []
            
            # 2. Fetch Intraday Data (Today)
            intraday_candles = self.api.get_intraday_candles(
                symbol=self.nifty_symbol,
                unit='minutes',
                interval=1
            ) or []
            
            # 3. Merge Datasets
            all_candles = historical_candles + intraday_candles
            
            if not all_candles:
                logger.warning("⚠️ No candle data available for ATR")
                return

            # 4. Process Data (Sort & Resample)
            df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Remove duplicates if any
            df.drop_duplicates(subset=['timestamp'], inplace=True)
            
            # Sort
            df.sort_values('timestamp', inplace=True)
            df.set_index('timestamp', inplace=True)
            
            # Resample to 5-minute candles
            ohlc_dict = {
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum',
                'oi': 'last'
            }
            
            df_5min = df.resample('5min').agg(ohlc_dict).dropna()
            
            # Log the last candle time to confirm freshness
            last_candle_time = df_5min.index[-1]
            logger.info(f"   Latest candle used for ATR: {last_candle_time}")
            
            # Convert back to list for calculation
            df_5min.reset_index(inplace=True)
            resampled_candles = df_5min.values.tolist()
            
            # 5. Calculate ATR
            self.daily_atr = self.calculate_atr(resampled_candles, period=self.atr_period)
            
            if self.daily_atr:
                logger.info(f"✅ Dynamic ATR ({self.atr_period} periods, 5-min) updated: {self.daily_atr:.2f}")
            else:
                logger.warning("⚠️ Failed to calculate Dynamic ATR")
                
        except Exception as e:
            logger.error(f"Error updating ATR: {e}")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main entry point"""
    
    # Validate configuration
    if CONFIG['ACCESS_TOKEN'] == 'your_upstox_access_token_here':
        logger.error("❌ Please set your Upstox access token in CONFIG")
        return
    
    # Auto-calculate Tuesday expiry for Nifty weekly options
    expiry_date = get_next_weekly_expiry()  # YYMMDD format
    expiry_full = get_next_weekly_expiry_full()  # YYYY-MM-DD format
    logger.info(f"📅 Auto-calculated Nifty weekly expiry (Tuesday): {expiry_full} ({expiry_date})")
    
    # Initialize API
    try:
        api = UpstoxAPI(CONFIG['ACCESS_TOKEN'])
        
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
    print("  5. Set EXECUTE_TRADES=True only when ready for live trading")
    print("\n" + "="*80 + "\n")
    
    # Confirmation for live trading
    if CONFIG['EXECUTE_TRADES']:
        print("⚠️  ⚠️  ⚠️  LIVE TRADING MODE ENABLED ⚠️  ⚠️  ⚠️")
        response = input("Are you sure you want to execute real trades? (yes/no): ")
        if response.lower() != 'yes':
            print("Exiting for safety. Set EXECUTE_TRADES=False for paper trading.")
            exit()
    
    main()