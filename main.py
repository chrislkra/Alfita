"""
Alpha Arena Style Trading Bot
Basado en las reglas ganadoras de DeepSeek en nof1.ai Alpha Arena
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Optional, Dict, List
import requests
import pandas as pd
import pandas_ta as ta
from binance.client import Client
from binance.enums import *
from dotenv import load_dotenv

load_dotenv()

# ============== CONFIGURACIÓN ==============
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Configuración del bot
TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT"]
LOOP_INTERVAL = 180  # 3 minutos entre decisiones
MAX_LEVERAGE = 20
DEFAULT_LEVERAGE = 10
CASH_BUFFER_PERCENT = 0.30  # 30% en reserva
MAX_POSITIONS = 6
DAILY_LOSS_LIMIT = 0.05  # -5% pausa el trading
INITIAL_BALANCE = 10000  # Para testnet

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self):
        # Binance Testnet
        self.client = Client(
            BINANCE_API_KEY, 
            BINANCE_SECRET_KEY,
            testnet=True
        )
        self.client.FUTURES_URL = 'https://testnet.binancefuture.com/fapi'
        
        self.positions: Dict[str, dict] = {}
        self.trade_history: List[dict] = []
        self.daily_pnl = 0.0
        self.starting_balance = INITIAL_BALANCE
        self.is_paused = False
        
        logger.info("🤖 Trading Bot iniciado - Modo Alpha Arena")
        self._setup_leverage()
    
    def _setup_leverage(self):
        """Configura leverage para todos los pares"""
        for pair in TRADING_PAIRS:
            try:
                self.client.futures_change_leverage(
                    symbol=pair, 
                    leverage=DEFAULT_LEVERAGE
                )
                logger.info(f"✅ Leverage {DEFAULT_LEVERAGE}x configurado para {pair}")
            except Exception as e:
                logger.warning(f"⚠️ Error configurando leverage para {pair}: {e}")
    
    def get_market_data(self) -> Dict[str, dict]:
        """Obtiene datos de mercado e indicadores para todos los pares"""
        market_data = {}
        
        for pair in TRADING_PAIRS:
            try:
                # Obtener velas (klines) - últimas 100 velas de 15min
                klines = self.client.futures_klines(
                    symbol=pair,
                    interval='15m',
                    limit=100
                )
                
                # Convertir a DataFrame
                df = pd.DataFrame(klines, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                    'taker_buy_quote', 'ignore'
                ])
                
                df['close'] = pd.to_numeric(df['close'])
                df['high'] = pd.to_numeric(df['high'])
                df['low'] = pd.to_numeric(df['low'])
                df['volume'] = pd.to_numeric(df['volume'])
                
                # Calcular indicadores con pandas-ta
                df['rsi'] = ta.rsi(df['close'], length=14)
                macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
                df['macd'] = macd['MACD_12_26_9']
                df['macd_signal'] = macd['MACDs_12_26_9']
                df['ema_20'] = ta.ema(df['close'], length=20)
                df['ema_50'] = ta.ema(df['close'], length=50)
                
                # Precio actual
                ticker = self.client.futures_symbol_ticker(symbol=pair)
                current_price = float(ticker['price'])
                
                # Último valor de indicadores
                market_data[pair] = {
                    'price': current_price,
                    'rsi': round(df['rsi'].iloc[-1], 2),
                    'macd': round(df['macd'].iloc[-1], 4),
                    'macd_signal': round(df['macd_signal'].iloc[-1], 4),
                    'ema_20': round(df['ema_20'].iloc[-1], 2),
                    'ema_50': round(df['ema_50'].iloc[-1], 2),
                    'volume_24h': round(df['volume'].sum(), 2),
                    'trend': 'BULLISH' if df['ema_20'].iloc[-1] > df['ema_50'].iloc[-1] else 'BEARISH'
                }
                
            except Exception as e:
                logger.error(f"❌ Error obteniendo datos de {pair}: {e}")
                market_data[pair] = None
        
        return market_data
    
    def get_account_info(self) -> dict:
        """Obtiene información de la cuenta"""
        try:
            account = self.client.futures_account()
            positions = self.client.futures_position_information()
            
            balance = float(account['totalWalletBalance'])
            unrealized_pnl = float(account['totalUnrealizedProfit'])
            available = float(account['availableBalance'])
            
            # Posiciones abiertas
            open_positions = []
            for pos in positions:
                if float(pos['positionAmt']) != 0:
                    open_positions.append({
                        'symbol': pos['symbol'],
                        'side': 'LONG' if float(pos['positionAmt']) > 0 else 'SHORT',
                        'size': abs(float(pos['positionAmt'])),
                        'entry_price': float(pos['entryPrice']),
                        'unrealized_pnl': float(pos['unRealizedProfit']),
                        'leverage': int(pos['leverage'])
                    })
            
            return {
                'balance': round(balance, 2),
                'unrealized_pnl': round(unrealized_pnl, 2),
                'available': round(available, 2),
                'equity': round(balance + unrealized_pnl, 2),
                'open_positions': open_positions,
                'position_count': len(open_positions)
            }
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo cuenta: {e}")
            return None
    
    def build_prompt(self, market_data: dict, account_info: dict) -> str:
        """Construye el prompt para DeepSeek siguiendo el formato Alpha Arena"""
        
        # System prompt (estilo Alpha Arena)
        system_prompt = """You are an autonomous crypto trading agent managing a portfolio on Binance Futures Testnet.

STRICT RULES (MUST FOLLOW):
1. Trade only: BTC, ETH, SOL, XRP, DOGE, BNB perpetuals (USDT pairs)
2. Leverage: 10x-20x maximum per position
3. Every trade MUST have Take-Profit (TP) and Stop-Loss (SL) defined
4. Keep 30% cash as buffer - NEVER go all-in
5. Maximum 6 open positions (one per coin)
6. If no clear setup exists → HOLD (doing nothing is valid)
7. Do NOT overtrade - quality over quantity
8. Do NOT add to losing positions (no martingale)
9. If daily loss exceeds 5% → recommend PAUSE

RISK MANAGEMENT:
- TP should be 1.5x to 3x the SL distance (positive risk/reward)
- SL should be 1-3% from entry for most trades
- Position size should risk max 2% of portfolio per trade

OUTPUT FORMAT (respond ONLY with this JSON structure):
{
    "action": "OPEN_LONG" | "OPEN_SHORT" | "CLOSE" | "ADJUST" | "HOLD",
    "symbol": "BTCUSDT",
    "leverage": 10,
    "size_percent": 10,
    "entry": 50000,
    "take_profit": 52000,
    "stop_loss": 49000,
    "confidence": 0.75,
    "reasoning": "Brief explanation"
}

For HOLD action, still provide reasoning why no trade is better.
For multiple actions, return an array of objects.
RESPOND ONLY WITH VALID JSON, NO ADDITIONAL TEXT."""

        # Market data section
        market_section = "CURRENT MARKET DATA:\n"
        for pair, data in market_data.items():
            if data:
                market_section += f"""
{pair}:
  Price: ${data['price']:,.2f}
  RSI(14): {data['rsi']}
  MACD: {data['macd']} (Signal: {data['macd_signal']})
  EMA20: ${data['ema_20']:,.2f} | EMA50: ${data['ema_50']:,.2f}
  Trend: {data['trend']}
"""
        
        # Account section
        account_section = f"""
ACCOUNT STATUS:
  Balance: ${account_info['balance']:,.2f}
  Unrealized PnL: ${account_info['unrealized_pnl']:,.2f}
  Equity: ${account_info['equity']:,.2f}
  Available: ${account_info['available']:,.2f}
  Open Positions: {account_info['position_count']}/6
"""
        
        # Open positions detail
        if account_info['open_positions']:
            account_section += "\nCURRENT POSITIONS:\n"
            for pos in account_info['open_positions']:
                account_section += f"  {pos['symbol']}: {pos['side']} {pos['size']} @ ${pos['entry_price']:,.2f} (PnL: ${pos['unrealized_pnl']:,.2f})\n"
        else:
            account_section += "\nCURRENT POSITIONS: None\n"
        
        # Combine prompt
        full_prompt = f"{system_prompt}\n\n{market_section}\n{account_section}\n\nBased on the current market conditions and account status, provide your trading decision:"
        
        return full_prompt
    
    def query_deepseek(self, prompt: str) -> Optional[dict]:
        """Consulta DeepSeek via OpenRouter"""
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/trading-bot",
                    "X-Title": "Alpha Arena Trading Bot"
                },
                json={
                    "model": "deepseek/deepseek-chat",  # DeepSeek V3
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,  # Bajo para decisiones más consistentes
                    "max_tokens": 1000
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                
                # Limpiar y parsear JSON
                content = content.strip()
                if content.startswith('```json'):
                    content = content[7:]
                if content.startswith('```'):
                    content = content[3:]
                if content.endswith('```'):
                    content = content[:-3]
                content = content.strip()
                
                decision = json.loads(content)
                logger.info(f"🧠 DeepSeek decisión: {decision}")
                return decision
            else:
                logger.error(f"❌ Error OpenRouter: {response.status_code} - {response.text}")
                return None
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error parseando respuesta JSON: {e}")
            logger.error(f"Respuesta raw: {content[:500]}")
            return None
        except Exception as e:
            logger.error(f"❌ Error consultando DeepSeek: {e}")
            return None
    
    def execute_trade(self, decision: dict) -> bool:
        """Ejecuta la orden basada en la decisión de DeepSeek"""
        try:
            action = decision.get('action', 'HOLD')
            symbol = decision.get('symbol', '')
            
            if action == 'HOLD':
                logger.info(f"⏸️ HOLD - {decision.get('reasoning', 'No action needed')}")
                return True
            
            if action in ['OPEN_LONG', 'OPEN_SHORT']:
                # Calcular tamaño de posición
                account = self.get_account_info()
                size_percent = decision.get('size_percent', 10) / 100
                leverage = decision.get('leverage', DEFAULT_LEVERAGE)
                
                # Respetar cash buffer
                max_usable = account['available'] * (1 - CASH_BUFFER_PERCENT)
                position_value = max_usable * size_percent
                
                # Obtener precio actual y calcular cantidad
                ticker = self.client.futures_symbol_ticker(symbol=symbol)
                current_price = float(ticker['price'])
                quantity = (position_value * leverage) / current_price
                
                # Redondear cantidad según el par
                quantity = self._round_quantity(symbol, quantity)
                
                if quantity <= 0:
                    logger.warning(f"⚠️ Cantidad calculada es 0 para {symbol}")
                    return False
                
                # Determinar lado
                side = SIDE_BUY if action == 'OPEN_LONG' else SIDE_SELL
                
                # Configurar leverage
                self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
                
                # Orden de mercado
                order = self.client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type=ORDER_TYPE_MARKET,
                    quantity=quantity
                )
                
                logger.info(f"✅ {action} ejecutado: {symbol} x{leverage} - Cantidad: {quantity}")
                
                # Configurar TP/SL
                tp_price = decision.get('take_profit')
                sl_price = decision.get('stop_loss')
                
                if tp_price and sl_price:
                    self._set_tp_sl(symbol, action, quantity, tp_price, sl_price)
                
                # Notificar
                self._notify(f"🟢 {action}\n{symbol} @ ${current_price:,.2f}\nSize: {quantity}\nLeverage: {leverage}x\nTP: ${tp_price:,.2f}\nSL: ${sl_price:,.2f}")
                
                return True
            
            elif action == 'CLOSE':
                # Cerrar posición existente
                positions = self.client.futures_position_information(symbol=symbol)
                for pos in positions:
                    pos_amt = float(pos['positionAmt'])
                    if pos_amt != 0:
                        side = SIDE_SELL if pos_amt > 0 else SIDE_BUY
                        quantity = abs(pos_amt)
                        
                        order = self.client.futures_create_order(
                            symbol=symbol,
                            side=side,
                            type=ORDER_TYPE_MARKET,
                            quantity=quantity,
                            reduceOnly=True
                        )
                        
                        logger.info(f"✅ Posición cerrada: {symbol}")
                        self._notify(f"🔴 CLOSE {symbol}\nReason: {decision.get('reasoning', 'N/A')}")
                        return True
                
                logger.warning(f"⚠️ No hay posición abierta en {symbol}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error ejecutando trade: {e}")
            self._notify(f"❌ Error ejecutando trade: {e}")
            return False
    
    def _set_tp_sl(self, symbol: str, action: str, quantity: float, tp_price: float, sl_price: float):
        """Configura Take Profit y Stop Loss"""
        try:
            # Determinar lados para TP/SL
            if action == 'OPEN_LONG':
                tp_side = SIDE_SELL
                sl_side = SIDE_SELL
            else:
                tp_side = SIDE_BUY
                sl_side = SIDE_BUY
            
            # Take Profit
            self.client.futures_create_order(
                symbol=symbol,
                side=tp_side,
                type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
                stopPrice=self._round_price(symbol, tp_price),
                quantity=quantity,
                reduceOnly=True
            )
            
            # Stop Loss
            self.client.futures_create_order(
                symbol=symbol,
                side=sl_side,
                type=FUTURE_ORDER_TYPE_STOP_MARKET,
                stopPrice=self._round_price(symbol, sl_price),
                quantity=quantity,
                reduceOnly=True
            )
            
            logger.info(f"✅ TP/SL configurados para {symbol}: TP=${tp_price}, SL=${sl_price}")
            
        except Exception as e:
            logger.error(f"❌ Error configurando TP/SL: {e}")
    
    def _round_quantity(self, symbol: str, quantity: float) -> float:
        """Redondea cantidad según las reglas del par"""
        # Precisiones comunes (ajustar según necesidad)
        precisions = {
            'BTCUSDT': 3,
            'ETHUSDT': 3,
            'SOLUSDT': 1,
            'XRPUSDT': 0,
            'DOGEUSDT': 0,
            'BNBUSDT': 2
        }
        precision = precisions.get(symbol, 3)
        return round(quantity, precision)
    
    def _round_price(self, symbol: str, price: float) -> float:
        """Redondea precio según las reglas del par"""
        precisions = {
            'BTCUSDT': 1,
            'ETHUSDT': 2,
            'SOLUSDT': 2,
            'XRPUSDT': 4,
            'DOGEUSDT': 5,
            'BNBUSDT': 2
        }
        precision = precisions.get(symbol, 2)
        return round(price, precision)
    
    def _notify(self, message: str):
        """Envía notificación a Telegram"""
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                requests.post(url, json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": f"🤖 Alpha Arena Bot\n\n{message}",
                    "parse_mode": "HTML"
                })
            except Exception as e:
                logger.warning(f"⚠️ Error enviando Telegram: {e}")
    
    def check_daily_loss(self) -> bool:
        """Verifica si se excedió el límite de pérdida diaria"""
        account = self.get_account_info()
        if account:
            current_equity = account['equity']
            daily_return = (current_equity - self.starting_balance) / self.starting_balance
            
            if daily_return <= -DAILY_LOSS_LIMIT:
                logger.warning(f"⚠️ Daily loss limit reached: {daily_return*100:.2f}%")
                self._notify(f"⚠️ PAUSA - Límite diario alcanzado: {daily_return*100:.2f}%")
                return True
        return False
    
    def run(self):
        """Loop principal del bot"""
        logger.info("🚀 Iniciando loop de trading...")
        self._notify("🚀 Bot iniciado - Modo Alpha Arena")
        
        while True:
            try:
                # Verificar límite diario
                if self.check_daily_loss():
                    logger.info("⏸️ Trading pausado por límite diario. Esperando reset...")
                    time.sleep(3600)  # Esperar 1 hora
                    continue
                
                # Obtener datos
                logger.info("📊 Obteniendo datos de mercado...")
                market_data = self.get_market_data()
                account_info = self.get_account_info()
                
                if not market_data or not account_info:
                    logger.warning("⚠️ No se pudieron obtener datos, reintentando...")
                    time.sleep(30)
                    continue
                
                # Construir prompt y consultar IA
                logger.info("🧠 Consultando DeepSeek...")
                prompt = self.build_prompt(market_data, account_info)
                decision = self.query_deepseek(prompt)
                
                if decision:
                    # Ejecutar decisión
                    if isinstance(decision, list):
                        for d in decision:
                            self.execute_trade(d)
                    else:
                        self.execute_trade(decision)
                else:
                    logger.warning("⚠️ No se obtuvo decisión válida de DeepSeek")
                
                # Log estado
                logger.info(f"💰 Balance: ${account_info['balance']:,.2f} | PnL: ${account_info['unrealized_pnl']:,.2f}")
                logger.info(f"⏳ Próxima decisión en {LOOP_INTERVAL} segundos...")
                
                time.sleep(LOOP_INTERVAL)
                
            except KeyboardInterrupt:
                logger.info("🛑 Bot detenido por usuario")
                self._notify("🛑 Bot detenido")
                break
            except Exception as e:
                logger.error(f"❌ Error en loop principal: {e}")
                time.sleep(60)


if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
