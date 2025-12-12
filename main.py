"""
Alpha Arena Style Trading Bot
Basado en las reglas ganadoras de DeepSeek en nof1.ai Alpha Arena
"""

import os
import json
import time
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, List
import requests
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator
from binance.client import Client
from binance.enums import *
from dotenv import load_dotenv
from prompts import get_system_prompt, get_mode_config

load_dotenv()

# Modelo gratis para chat de Telegram
FREE_CHAT_MODEL = "meta-llama/llama-3.2-3b-instruct:free"

# ============== CONFIGURACIÓN ==============
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============== CONFIGURACIÓN ==============
# Monk Mode: mismo config que baseline, diferencia es el prompt
TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT"]
TRADING_PAIRS_SHORT = ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"]  # Para el output de la IA
LOOP_INTERVAL = 120  # 2 minutos entre decisiones (Alpha Arena style)
MAX_LEVERAGE = 20
DEFAULT_LEVERAGE = 10
CASH_BUFFER_PERCENT = 0.30  # 30% en reserva
MAX_POSITIONS = 6
MIN_CONFIDENCE = 0.70  # Monk Mode: >0.7 confianza
DAILY_LOSS_LIMIT = 0.05  # -5% pausa el trading
INITIAL_BALANCE = 10000  # Para testnet
TRADING_MODE = "monk_mode"  # baseline, monk_mode, max_leverage

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
        self.trade_history: List[dict] = []  # Historial con razones
        self.daily_pnl = 0.0
        self.is_paused = False
        self.last_update_id = 0  # Para polling de Telegram

        logger.info("🤖 Trading Bot iniciado - Modo Alpha Arena")
        self._setup_leverage()

        # Cerrar todas las posiciones existentes para empezar limpio
        self._close_all_positions()

        # Usar balance actual como punto de partida
        account = self.client.futures_account()
        self.starting_balance = float(account['totalWalletBalance'])
        logger.info(f"💰 Balance inicial: ${self.starting_balance:.2f}")

        # Iniciar listener de Telegram en hilo separado
        if TELEGRAM_BOT_TOKEN:
            self.telegram_thread = threading.Thread(target=self._telegram_listener, daemon=True)
            self.telegram_thread.start()
            logger.info("📱 Telegram listener iniciado")

    def _close_all_positions(self):
        """Cierra todas las posiciones abiertas al iniciar"""
        try:
            positions = self.client.futures_position_information()
            for pos in positions:
                amt = float(pos['positionAmt'])
                if amt != 0:
                    symbol = pos['symbol']
                    side = 'SELL' if amt > 0 else 'BUY'
                    qty = abs(amt)
                    self.client.futures_create_order(
                        symbol=symbol,
                        side=side,
                        type='MARKET',
                        quantity=qty,
                        reduceOnly=True
                    )
                    logger.info(f"🧹 Cerrada posición {symbol}: {amt}")
            logger.info("✅ Todas las posiciones cerradas - empezando limpio")
        except Exception as e:
            logger.warning(f"⚠️ Error cerrando posiciones: {e}")

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
                
                # Calcular indicadores con ta
                df['rsi'] = RSIIndicator(df['close'], window=14).rsi()
                macd_indicator = MACD(df['close'], window_fast=12, window_slow=26, window_sign=9)
                df['macd'] = macd_indicator.macd()
                df['macd_signal'] = macd_indicator.macd_signal()
                df['ema_20'] = EMAIndicator(df['close'], window=20).ema_indicator()
                df['ema_50'] = EMAIndicator(df['close'], window=50).ema_indicator()
                
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

                # Logging de diagnóstico
                logger.info(f"📊 MARKET DATA: {pair}: price=${current_price:,.2f}, vol=${market_data[pair]['volume_24h']:,.2f}")
                logger.info(f"📈 INDICATORS: {pair}: RSI={market_data[pair]['rsi']}, MACD={market_data[pair]['macd']}, Signal={market_data[pair]['macd_signal']}, EMA20=${market_data[pair]['ema_20']:,.2f}, EMA50=${market_data[pair]['ema_50']:,.2f}")

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
        """Construye el prompt para DeepSeek usando el modo configurado"""

        # Obtener system prompt del modo actual (Monk Mode)
        system_prompt = get_system_prompt(TRADING_MODE)

        # Market data section
        market_section = "\n\nCURRENT MARKET DATA (15-min candles):\n"
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

        # Account section - actualizado para Monk Mode (max 3 posiciones)
        account_section = f"""
ACCOUNT STATUS:
  Balance: ${account_info['balance']:,.2f}
  Unrealized PnL: ${account_info['unrealized_pnl']:,.2f}
  Equity: ${account_info['equity']:,.2f}
  Available: ${account_info['available']:,.2f}
  Open Positions: {account_info['position_count']}/{MAX_POSITIONS}
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
            # Logging del payload completo
            payload = {
                "model": "deepseek/deepseek-chat",  # DeepSeek V3
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,  # Bajo para decisiones más consistentes
                "max_tokens": 1000
            }
            logger.info(f"🧠 DEEPSEEK PAYLOAD: {json.dumps(payload, indent=2)}")

            # Medir tiempo de respuesta
            start_time = time.time()

            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/trading-bot",
                    "X-Title": "Alpha Arena Trading Bot"
                },
                json=payload,
                timeout=60
            )

            elapsed_time = time.time() - start_time
            logger.info(f"⏱️ DeepSeek response time: {elapsed_time:.2f}s")

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
    
    def _save_trade(self, action: str, symbol: str, reasoning: str, price: float = 0, quantity: float = 0):
        """Guarda trade en historial"""
        self.trade_history.append({
            'action': action,
            'symbol': symbol,
            'reasoning': reasoning,
            'price': price,
            'quantity': quantity,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M")
        })
        # Mantener solo últimos 50 trades
        if len(self.trade_history) > 50:
            self.trade_history = self.trade_history[-50:]

    def _coin_to_symbol(self, coin: str) -> str:
        """Convierte coin (BTC) a symbol (BTCUSDT)"""
        coin = coin.upper()
        if coin.endswith("USDT"):
            return coin
        return f"{coin}USDT"

    def execute_trade(self, decision: dict) -> bool:
        """Ejecuta la orden basada en la decisión de DeepSeek"""
        try:
            # Nuevo formato Alpha Arena
            signal = decision.get('signal', 'hold')
            coin = decision.get('coin', '')
            symbol = self._coin_to_symbol(coin) if coin else ''
            justification = decision.get('justification', 'No reason provided')
            confidence = decision.get('confidence', 0)
            quantity = decision.get('quantity', 0)
            leverage = decision.get('leverage', DEFAULT_LEVERAGE)
            tp_price = decision.get('profit_target', 0)
            sl_price = decision.get('stop_loss', 0)
            invalidation = decision.get('invalidation_condition', '')

            if signal == 'hold':
                logger.info(f"⏸️ HOLD - {justification}")
                return True

            # Verificar confianza mínima
            if signal in ['buy_to_enter', 'sell_to_enter'] and confidence < MIN_CONFIDENCE:
                logger.info(f"⏸️ SKIP - Confianza {confidence*100:.0f}% < {MIN_CONFIDENCE*100:.0f}% requerida. {justification}")
                return True

            if signal in ['buy_to_enter', 'sell_to_enter']:
                account = self.get_account_info()

                # Usar quantity de la IA o calcular
                if quantity <= 0:
                    # Calcular basado en risk_usd o 10% del disponible
                    risk_usd = decision.get('risk_usd', account['available'] * 0.10)
                    ticker = self.client.futures_symbol_ticker(symbol=symbol)
                    current_price = float(ticker['price'])
                    quantity = (risk_usd * leverage) / current_price
                else:
                    ticker = self.client.futures_symbol_ticker(symbol=symbol)
                    current_price = float(ticker['price'])

                # Redondear cantidad
                quantity = self._round_quantity(symbol, quantity)

                if quantity <= 0:
                    logger.warning(f"⚠️ Cantidad calculada es 0 para {symbol}")
                    return False

                # Determinar lado
                side = SIDE_BUY if signal == 'buy_to_enter' else SIDE_SELL
                action = 'OPEN_LONG' if signal == 'buy_to_enter' else 'OPEN_SHORT'

                # Configurar leverage
                leverage = min(leverage, MAX_LEVERAGE)
                self.client.futures_change_leverage(symbol=symbol, leverage=leverage)

                # Orden de mercado
                order = self.client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type=ORDER_TYPE_MARKET,
                    quantity=quantity
                )

                logger.info(f"✅ {action} ejecutado: {symbol} x{leverage} - Cantidad: {quantity}")

                # Guardar en historial
                self._save_trade(action, symbol, justification, current_price, quantity)

                # Configurar TP/SL
                if tp_price and sl_price:
                    self._set_tp_sl(symbol, action, quantity, tp_price, sl_price)

                # Notificar
                msg = f"🟢 *{action}*\n"
                msg += f"📍 {symbol} @ ${current_price:,.2f}\n"
                msg += f"📊 Size: {quantity} | Leverage: {leverage}x\n"
                if tp_price and sl_price:
                    msg += f"🎯 TP: ${tp_price:,.2f} | SL: ${sl_price:,.2f}\n"
                if invalidation:
                    msg += f"❌ Invalidación: {invalidation}\n"
                msg += f"\n💬 _{justification}_"
                self._notify(msg)

                return True

            elif signal == 'close':
                # Cerrar posición existente
                positions = self.client.futures_position_information(symbol=symbol)
                for pos in positions:
                    pos_amt = float(pos['positionAmt'])
                    if pos_amt != 0:
                        side = SIDE_SELL if pos_amt > 0 else SIDE_BUY
                        quantity = abs(pos_amt)
                        entry_price = float(pos['entryPrice'])

                        order = self.client.futures_create_order(
                            symbol=symbol,
                            side=side,
                            type=ORDER_TYPE_MARKET,
                            quantity=quantity,
                            reduceOnly=True
                        )

                        logger.info(f"✅ Posición cerrada: {symbol}")

                        # Guardar en historial
                        self._save_trade('CLOSE', symbol, justification, entry_price, quantity)

                        # Notificar
                        msg = f"🔴 *CLOSE*\n"
                        msg += f"📍 {symbol}\n"
                        msg += f"\n💬 _{justification}_"
                        self._notify(msg)
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
            if action in ['OPEN_LONG', 'buy_to_enter']:
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
    
    def _telegram_listener(self):
        """Escucha mensajes de Telegram en loop"""
        logger.info("📱 Iniciando Telegram polling...")
        while True:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
                response = requests.get(url, params={
                    "offset": self.last_update_id + 1,
                    "timeout": 30
                }, timeout=35)

                if response.status_code == 200:
                    updates = response.json().get("result", [])
                    for update in updates:
                        self.last_update_id = update["update_id"]
                        if "message" in update:
                            self._handle_telegram_message(update["message"])
            except Exception as e:
                logger.warning(f"⚠️ Error en Telegram polling: {e}")
                time.sleep(5)

    def _handle_telegram_message(self, message: dict):
        """Procesa mensajes de Telegram"""
        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip()

        if not text:
            return

        # Comandos con /
        if text.startswith("/"):
            cmd = text.split()[0].lower()
            if cmd == "/start":
                self._send_telegram(chat_id, "🤖 *Alpha Arena Bot*\n\nComandos:\n/status - Ver posiciones y balance\n/history - Ver historial de trades\n/market - Ver datos de mercado\n\nO escribe cualquier pregunta sobre el mercado.")
            elif cmd == "/status":
                self._cmd_status(chat_id)
            elif cmd == "/history":
                self._cmd_history(chat_id)
            elif cmd == "/market":
                self._cmd_market(chat_id)
            else:
                self._send_telegram(chat_id, "Comando no reconocido. Usa /start para ver comandos.")
        else:
            # Chat natural con modelo gratis
            self._cmd_chat(chat_id, text)

    def _cmd_status(self, chat_id: int):
        """Comando /status - muestra posiciones y balance"""
        try:
            account = self.get_account_info()
            if not account:
                self._send_telegram(chat_id, "❌ Error obteniendo datos de cuenta")
                return

            msg = f"📊 *Estado de la Cuenta*\n\n"
            msg += f"💰 Balance: ${account['balance']:,.2f}\n"
            msg += f"📈 PnL No Realizado: ${account['unrealized_pnl']:,.2f}\n"
            msg += f"💵 Equity: ${account['equity']:,.2f}\n"
            msg += f"🏦 Disponible: ${account['available']:,.2f}\n"
            msg += f"📍 Posiciones: {account['position_count']}/6\n\n"

            if account['open_positions']:
                msg += "*Posiciones Abiertas:*\n"
                for pos in account['open_positions']:
                    emoji = "🟢" if pos['unrealized_pnl'] >= 0 else "🔴"
                    msg += f"{emoji} {pos['symbol']} {pos['side']}\n"
                    msg += f"   Size: {pos['size']} @ ${pos['entry_price']:,.2f}\n"
                    msg += f"   PnL: ${pos['unrealized_pnl']:,.2f}\n"
            else:
                msg += "_Sin posiciones abiertas_"

            self._send_telegram(chat_id, msg)
        except Exception as e:
            self._send_telegram(chat_id, f"❌ Error: {e}")

    def _cmd_history(self, chat_id: int):
        """Comando /history - muestra historial de trades"""
        if not self.trade_history:
            self._send_telegram(chat_id, "📜 *Historial de Trades*\n\n_No hay trades registrados aún_")
            return

        msg = "📜 *Historial de Trades*\n\n"
        for i, trade in enumerate(self.trade_history[-10:], 1):  # Últimos 10
            emoji = "🟢" if trade['action'] in ['OPEN_LONG', 'OPEN_SHORT'] else "🔴"
            msg += f"{emoji} *{trade['action']}* {trade['symbol']}\n"
            msg += f"   📅 {trade['timestamp']}\n"
            msg += f"   💬 _{trade['reasoning']}_\n\n"

        self._send_telegram(chat_id, msg)

    def _cmd_market(self, chat_id: int):
        """Comando /market - muestra datos de mercado"""
        try:
            market_data = self.get_market_data()
            msg = "📈 *Datos de Mercado*\n\n"

            for pair, data in market_data.items():
                if data:
                    trend_emoji = "🟢" if data['trend'] == 'BULLISH' else "🔴"
                    msg += f"*{pair}* {trend_emoji}\n"
                    msg += f"  💵 ${data['price']:,.2f}\n"
                    msg += f"  RSI: {data['rsi']} | {data['trend']}\n\n"

            self._send_telegram(chat_id, msg)
        except Exception as e:
            self._send_telegram(chat_id, f"❌ Error: {e}")

    def _cmd_chat(self, chat_id: int, question: str):
        """Chat natural con modelo gratis"""
        try:
            # Obtener contexto actual
            account = self.get_account_info()
            market_data = self.get_market_data()

            context = f"""Eres un asistente de trading crypto. Responde en español, breve y útil.

Datos actuales:
- Balance: ${account['balance']:,.2f}
- PnL: ${account['unrealized_pnl']:,.2f}
- Posiciones abiertas: {account['position_count']}/6

Mercado:
"""
            for pair, data in market_data.items():
                if data:
                    context += f"- {pair}: ${data['price']:,.2f}, RSI={data['rsi']}, {data['trend']}\n"

            context += f"\nPregunta del usuario: {question}"

            # Llamar modelo gratis
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": FREE_CHAT_MODEL,
                    "messages": [{"role": "user", "content": context}],
                    "max_tokens": 500
                },
                timeout=30
            )

            if response.status_code == 200:
                answer = response.json()['choices'][0]['message']['content']
                self._send_telegram(chat_id, f"🤖 {answer}")
            else:
                self._send_telegram(chat_id, "❌ Error consultando IA")

        except Exception as e:
            self._send_telegram(chat_id, f"❌ Error: {e}")

    def _send_telegram(self, chat_id: int, message: str):
        """Envía mensaje a un chat específico"""
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown"
            })
        except Exception as e:
            logger.warning(f"⚠️ Error enviando Telegram: {e}")

    def _notify(self, message: str):
        """Envía notificación a Telegram (broadcast)"""
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                requests.post(url, json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": f"🤖 Alpha Arena Bot\n\n{message}",
                    "parse_mode": "Markdown"
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
