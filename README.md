# 🤖 Alpha Arena Trading Bot

Bot de trading automatizado basado en las reglas ganadoras de **DeepSeek** en la competencia [Alpha Arena](https://nof1.ai).

## 📊 Resultados de Alpha Arena

DeepSeek logró **+35% en 3 días** y hasta **+94.8%** en algunas sesiones usando estas reglas.

## 🏗️ Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                     RAILWAY                              │
│  ┌─────────────────────────────────────────────────┐    │
│  │              TRADING BOT (Python)                │    │
│  │                                                  │    │
│  │  Binance API ──→ Datos de mercado (3 min)       │    │
│  │  pandas-ta ──→ RSI, MACD, EMA                   │    │
│  │  OpenRouter ──→ DeepSeek V3 decisiones          │    │
│  │  Binance Testnet ──→ Ejecuta órdenes            │    │
│  │  Telegram ──→ Notificaciones (opcional)         │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

## 🚀 Deployment en Railway

### Paso 1: Obtener API Keys

#### OpenRouter (DeepSeek)
1. Ve a [openrouter.ai](https://openrouter.ai)
2. Crea una cuenta
3. Ve a **Keys** → **Create Key**
4. Copia el API key (`sk-or-v1-...`)

#### Binance Futures Testnet
1. Ve a [testnet.binancefuture.com](https://testnet.binancefuture.com)
2. Inicia sesión con GitHub
3. Ve a **API Management** (arriba derecha)
4. Click **Create API**
5. Copia **API Key** y **Secret Key**
6. ⚠️ Asegúrate de habilitar **Futures** permissions

#### Telegram (Opcional)
1. Habla con [@BotFather](https://t.me/BotFather) en Telegram
2. Envía `/newbot` y sigue las instrucciones
3. Copia el **Bot Token**
4. Habla con [@userinfobot](https://t.me/userinfobot) para obtener tu **Chat ID**

### Paso 2: Deploy en Railway

#### Opción A: Deploy directo desde GitHub

1. Sube este código a un repositorio de GitHub
2. Ve a [railway.app](https://railway.app)
3. Click **New Project** → **Deploy from GitHub repo**
4. Selecciona tu repositorio
5. Railway detectará el Dockerfile automáticamente

#### Opción B: Deploy desde CLI

```bash
# Instalar Railway CLI
npm install -g @railway/cli

# Login
railway login

# Crear proyecto
railway init

# Deploy
railway up
```

### Paso 3: Configurar Variables de Entorno

En Railway Dashboard:
1. Click en tu proyecto
2. Ve a **Variables**
3. Agrega estas variables:

| Variable | Valor |
|----------|-------|
| `OPENROUTER_API_KEY` | `sk-or-v1-xxxxx` |
| `BINANCE_API_KEY` | `tu-api-key` |
| `BINANCE_SECRET_KEY` | `tu-secret-key` |
| `TELEGRAM_BOT_TOKEN` | `opcional` |
| `TELEGRAM_CHAT_ID` | `opcional` |

### Paso 4: Ver Logs

```bash
railway logs
```

O en el Dashboard: Click proyecto → **Deployments** → **View Logs**

## ⚙️ Configuración

Edita estas variables en `main.py` según tu preferencia:

```python
TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT"]
LOOP_INTERVAL = 180          # Segundos entre decisiones (3 min)
MAX_LEVERAGE = 20            # Máximo leverage permitido
DEFAULT_LEVERAGE = 10        # Leverage por defecto
CASH_BUFFER_PERCENT = 0.30   # 30% en reserva
MAX_POSITIONS = 6            # Máximo posiciones abiertas
DAILY_LOSS_LIMIT = 0.05      # -5% pausa el trading
```

## 🧠 Reglas de Trading (Alpha Arena Style)

1. **Diversificación**: Máximo 1 posición por par, 6 posiciones total
2. **Cash Buffer**: Siempre mantener 30% en reserva
3. **TP/SL Obligatorio**: Cada trade debe tener Take Profit y Stop Loss
4. **No Overtrade**: Si no hay setup claro → HOLD
5. **Límite Diario**: Si pierde -5% → Pausa automática
6. **Leverage Moderado**: 10-20x máximo

## 📁 Estructura de Archivos

```
trading-bot/
├── main.py              # Bot principal
├── requirements.txt     # Dependencias Python
├── Dockerfile          # Para Railway
├── .env.example        # Ejemplo de variables
└── README.md           # Este archivo
```

## 🔒 Seguridad

- ✅ Solo usa Testnet hasta validar la estrategia
- ✅ Nunca compartas tus API keys
- ✅ Usa API keys con permisos mínimos necesarios
- ✅ El bot guarda logs localmente, revísalos regularmente

## 📊 Monitoreo

### Logs
Los logs se guardan en `trading_bot.log` y también se muestran en consola.

### Telegram
Si configuras Telegram, recibirás:
- 🟢 Notificación de trades abiertos
- 🔴 Notificación de trades cerrados
- ⚠️ Alertas de límites alcanzados
- 🚀 Inicio/parada del bot

## 🛠️ Desarrollo Local

```bash
# Clonar repositorio
git clone <tu-repo>
cd trading-bot

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o: venv\Scripts\activate  # Windows

# Instalar dependencias
pip install -r requirements.txt

# Copiar y editar variables de entorno
cp .env.example .env
# Editar .env con tus API keys

# Ejecutar
python main.py
```

## ⚠️ Disclaimer

Este bot es para **propósitos educativos**. El trading de criptomonedas con leverage es extremadamente riesgoso. 

- Usa solo dinero que puedas permitirte perder
- Testea exhaustivamente en testnet primero
- Los resultados pasados no garantizan resultados futuros
- No somos responsables de pérdidas financieras

## 📜 Licencia

MIT License - Usa bajo tu propio riesgo.

---

Inspirado por el experimento [Alpha Arena](https://nof1.ai) de nof1.ai
