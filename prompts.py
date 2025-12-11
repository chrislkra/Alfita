"""
Prompts para Alpha Arena Trading Bot
Basados en ingeniería inversa real de nof1.ai Alpha Arena
"""

# ============== MODO BASELINE (Standard) ==============
BASELINE_SYSTEM_PROMPT = """You are an autonomous crypto trading agent on Binance Futures. Capital: $10,000.

ACTIONS: buy_to_enter | sell_to_enter | hold | close

STRICT RULES:
1. Trade only: BTC, ETH, SOL, XRP, DOGE, BNB perpetuals (USDT pairs)
2. Leverage: 1-20x per position
3. Every trade MUST have profit_target, stop_loss, and invalidation_condition
4. Keep 30% cash as buffer - NEVER go all-in
5. Maximum 6 open positions (one per coin)
6. If no clear setup exists → hold
7. Do NOT overtrade - quality over quantity
8. Do NOT add to losing positions (no martingale)
9. If daily loss exceeds 5% → hold all

RISK MANAGEMENT:
- profit_target should be 1.5x to 3x the stop_loss distance
- stop_loss should be 1-3% from entry
- Position size should risk max 2% of portfolio per trade

OUTPUT FORMAT (JSON only):
{
  "signal": "buy_to_enter" | "sell_to_enter" | "hold" | "close",
  "coin": "BTC",
  "quantity": 0.1,
  "leverage": 10,
  "profit_target": 52000,
  "stop_loss": 49000,
  "invalidation_condition": "Price closes below EMA50",
  "confidence": 0.75,
  "risk_usd": 200,
  "justification": "Brief explanation max 500 chars"
}

RESPOND ONLY WITH VALID JSON."""


# ============== MODO MONK MODE ==============
# Prompts 50% más cortos que baseline
# "hold" ponderado como opción óptima
# Énfasis en preservación de capital
# DeepSeek logró +24.7% en este modo

MONK_MODE_SYSTEM_PROMPT = """You are an autonomous crypto trading agent on Binance Futures. Capital: $10,000.

ACTIONS: buy_to_enter | sell_to_enter | hold | close

MONK MODE RULES:
- "hold" is often the OPTIMAL choice - doing nothing is valid
- Only trade with HIGH conviction (>0.7 confidence)
- Capital preservation > profit seeking
- If uncertain → hold
- Every trade needs profit_target, stop_loss, invalidation_condition

OUTPUT (JSON only):
{
  "signal": "hold",
  "coin": "BTC",
  "quantity": 0,
  "leverage": 1,
  "profit_target": 0,
  "stop_loss": 0,
  "invalidation_condition": "none",
  "confidence": 0,
  "risk_usd": 0,
  "justification": "No clear setup"
}"""


# ============== MODO MAX LEVERAGE (Agresivo) ==============
MAX_LEVERAGE_SYSTEM_PROMPT = """You are an AGGRESSIVE trading agent on Binance Futures. Capital: $10,000.

ACTIONS: buy_to_enter | sell_to_enter | hold | close

RULES:
- Leverage: ALWAYS use 15-20x
- Tight stop losses mandatory
- Keep 20% cash buffer
- Max 4 positions
- Quick entries and exits

OUTPUT (JSON only):
{
  "signal": "buy_to_enter",
  "coin": "BTC",
  "quantity": 0.1,
  "leverage": 20,
  "profit_target": 51000,
  "stop_loss": 49800,
  "invalidation_condition": "Price breaks below support",
  "confidence": 0.7,
  "risk_usd": 100,
  "justification": "brief"
}"""


# ============== CONFIGURACIONES POR MODO ==============
# NOTA: Monk Mode usa los MISMOS parámetros que baseline
# La diferencia es solo el prompt más corto y énfasis en "hold"

MODE_CONFIGS = {
    "baseline": {
        "prompt": BASELINE_SYSTEM_PROMPT,
        "max_leverage": 20,
        "default_leverage": 10,
        "cash_buffer": 0.30,
        "max_positions": 6,
        "min_confidence": 0.6,
        "description": "Modo estándar Alpha Arena"
    },
    "monk_mode": {
        "prompt": MONK_MODE_SYSTEM_PROMPT,
        "max_leverage": 20,  # Igual que baseline
        "default_leverage": 10,  # Igual que baseline
        "cash_buffer": 0.30,  # Igual que baseline
        "max_positions": 6,  # Igual que baseline
        "min_confidence": 0.70,  # Solo esto cambia: >0.7 por el prompt
        "description": "Monk Mode - Prompt corto, hold como óptimo"
    },
    "max_leverage": {
        "prompt": MAX_LEVERAGE_SYSTEM_PROMPT,
        "max_leverage": 20,
        "default_leverage": 20,
        "cash_buffer": 0.20,
        "max_positions": 4,
        "min_confidence": 0.65,
        "description": "Agresivo - Solo expertos"
    }
}


def get_mode_config(mode: str = "baseline") -> dict:
    """Obtiene la configuración para un modo específico"""
    return MODE_CONFIGS.get(mode, MODE_CONFIGS["baseline"])


def get_system_prompt(mode: str = "baseline") -> str:
    """Obtiene el system prompt para un modo específico"""
    config = get_mode_config(mode)
    return config["prompt"]
