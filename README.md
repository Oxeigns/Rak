# AI Governor Bot - Revolutionary Telegram Group Management

## 🚀 Deploy to Heroku

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/Oxeigns/Rak.git)


### One-click Heroku Deploy

Use the button below to deploy this exact repository on l)](LICENSE)

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Mathematical Risk Scoring](#mathematical-risk-scoring)
4. [Features](#features)
5. [Installation](#installation)
6. [Deployment](#deployment)
7. [Configuration](#configuration)
8. [Security](#security)
9. [Scaling Strategy](#scaling-strategy)
10. [Cost Estimation](#cost-estimation)
11. [Roadmap](#roadmap)

---

## Overview

AI Governor is a **fully autonomous**, enterprise-grade Telegram group management system powered by advanced AI. Unlike traditional keyword-based moderation bots, AI Governor uses **semantic analysis** and **behavioral intelligence** to understand context, detect sophisticated spam, and protect communities with unprecedented accuracy.

### Key Differentiators

- **Zero-setup deployment**: Works instantly when added
- **AI-driven moderation**: Semantic understanding, not just keywords
- **Behavioral intelligence**: Trust score engine learns user patterns
- **Anti-raid protection**: Detects coordinated attacks in real-time
- **Multi-language support**: Native support for English, Hindi, Hinglish
- **Premium UX**: Smooth inline control panel, minimal message spam

---

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         TELEGRAM API                            │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FASTAPI WEBHOOK SERVER                     │
│                     (python-telegram-bot)                       │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MESSAGE PROCESSOR                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Preprocessor │→ │ Risk Engine  │→ │ Decision Executor    │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└────────────────────┬────────────────────────────────────────────┘
                     │
    ┌────────────────┼────────────────┐
    │                │                │
    ▼                ▼                ▼
┌──────────┐  ┌──────────┐  ┌────────────────┐
│ AI Service│  │ Trust    │  │ Anti-Raid      │
│ (HF Router)│ │ Engine   │  │ System         │
└──────────┘  └──────────┘  └────────────────┘
    │                │                │
    └────────────────┼────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DATA LAYER                                 │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │ PostgreSQL       │  │ Redis Cache      │                    │
│  │ (Persistent)     │  │ (Session/Queue)  │                    │
│  └──────────────────┘  └──────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
```

### Component Breakdown

#### 1. FastAPI Webhook Server
- **Purpose**: Handle Telegram webhook events
- **Technology**: FastAPI + python-telegram-bot
- **Scaling**: Stateless, horizontally scalable

#### 2. Message Processor
- **Preprocessor**: Unicode normalization, link extraction, language detection
- **Risk Engine**: Multi-factor risk calculation (detailed below)
- **Decision Executor**: Apply actions based on risk thresholds

#### 3. AI Service
- **Primary**: Hugging Face Router models for semantic content analysis
- **Fallback**: Rule-based system if AI unavailable
- **Caching**: 24-hour cache to reduce API costs

### OpenAI → Hugging Face Router conversion helper

This repository includes `utils/openai_to_hf_router_converter.py` to automatically
convert common OpenAI Python API patterns into Hugging Face Router API calls.

Install requirements for conversion/runtime:

```bash
pip install huggingface_hub requests transformers
```

Set your Hugging Face token:

```bash
export HUGGINGFACE_TOKEN="hf_xxxxxYOURKEYxxxxx"
```

For Heroku:

```bash
heroku config:set HUGGINGFACE_TOKEN=hf_xxxxxYOURKEYxxxxx
```

Run a minimal decision API smoke test:

```bash
python utils/hf_router_decision_example.py
```

#### 4. Trust Engine
- **Formula**: `T_new = T_old + (positive × 0.8) - (violations × 5) - (mute × 8) - (ban × 15)`
- **Decay**: Inactive users lose trust over time
- **Restrictions**: Automatic restrictions based on score

#### 5. Anti-Raid System
- **Triggers**: Mass joins, new account waves, username patterns
- **Actions**: Auto-slow mode, join restrictions, admin alerts
- **Detection**: Statistical pattern matching

---

## Mathematical Risk Scoring

### Core Formula

The risk scoring engine uses a **weighted multi-factor probability formula**:

```
R = 1 - Π(1 - Wi × Si)

Where:
- R = Final risk score (0-1)
- Wi = Weight of factor i
- Si = Normalized score of factor i
- Π = Product of all (1 - Wi × Si)
```

### Risk Factors & Weights

| Factor | Weight | Description |
|--------|--------|-------------|
| Spam | 0.18 | Promotional content probability |
| Toxicity | 0.14 | Hate speech/harassment |
| Scam | 0.16 | Fraudulent intent |
| Illegal | 0.18 | Criminal content |
| Phishing | 0.14 | Credential theft |
| NSFW | 0.12 | Adult content |
| Flood | 0.10 | Message velocity |
| User History | 0.10 | Past violations |
| Similarity | 0.08 | Duplicate detection |
| Link Suspicious | 0.10 | Suspicious URLs |

### Dynamic Escalation

```python
# Violation count escalation
if violations_24h > 3:
    R *= 1.15

# Trust score escalation  
if trust_score < 20:
    R *= 1.25
```

### Sigmoid Smoothing

To ensure fair scoring distribution:

```
R_final = 1 / (1 + e^(-k(R - 0.5)))

Where k = 10 (steepness parameter)
```

### Decision Thresholds

| Score Range | Risk Level | Action |
|-------------|------------|--------|
| ≥ 85 | Critical | Delete + Mute + Notify |
| 70-85 | High | Delete + Warn |
| 50-70 | Medium | Soft Warning |
| < 50 | Low | Allow |

---

## Features

### Core Protection Features

- **Spam Shield**: AI-powered spam detection
- **AI Abuse Detection**: Context-aware toxicity analysis
- **Link Intelligence**: Suspicious URL detection
- **Anti-Raid System**: Mass join detection
- **Trust Score Engine**: Behavioral reputation system
- **Media Scanner**: NSFW and violent content detection

### Optional Premium Features

- **Strict Mode**: Lower thresholds, zero tolerance
- **Crypto Scam Shield**: Specialized crypto scam detection
- **Deep Media Analysis**: Frame-by-frame video analysis
- **Engagement Engine**: Automated community building
- **Analytics Dashboard**: Comprehensive group insights

### Control Panel Menus

```
Main Menu
├── Protection Settings
│   ├── Spam Shield (toggle)
│   ├── AI Abuse Detection (toggle)
│   ├── Link Intelligence (toggle)
│   ├── Strict Mode (toggle)
│   ├── Crypto Scam Shield (toggle)
│   └── Deep Media Analysis (toggle)
├── Engagement Engine
│   ├── Daily Question (toggle)
│   ├── Weekly Poll (toggle)
│   ├── Member Spotlight (toggle)
│   ├── Leaderboard (toggle)
│   └── Achievement Badges (toggle)
├── Trust System
│   ├── View Leaderboard
│   ├── Edit Thresholds
│   └── Reset Scores
├── Raid Protection
│   ├── Auto-Protect (toggle)
│   ├── Join Threshold (edit)
│   ├── Time Window (edit)
│   └── Emergency Lockdown
├── Analytics
│   ├── Daily Report
│   ├── Weekly Report
│   ├── Monthly Report
│   └── Export Data
├── Personality Mode
│   ├── Friendly
│   ├── Strict
│   ├── Corporate
│   ├── Funny
│   └── Owner-Style
├── Language
│   ├── English
│   ├── Hindi
│   └── Hinglish
├── Advanced AI Settings
│   ├── Context Window
│   ├── Personality Strength
│   ├── Multi-language
│   └── Context Awareness
└── System Status
    ├── Refresh Status
    ├── View Logs
    └── API Usage
```

---

## Installation

### Local Development

```bash
# Clone repository
git clone https://github.com/yourusername/ai-governor-bot.git
cd ai-governor-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup environment variables
cp .env.example .env
# Edit .env with your tokens

# Run database migrations
python -c "import asyncio; from models.database import db_manager; asyncio.run(db_manager.initialize()); asyncio.run(db_manager.create_tables())"

# Start bot
python main.py
```


### Hugging Face Setup

```bash
pip install huggingface_hub requests transformers
export HUGGINGFACE_TOKEN="hf_xxxxxYOURKEYxxxxx"
```

For Heroku:

```bash
heroku config:set HUGGINGFACE_TOKEN=hf_xxxxxYOURKEYxxxxx
```

Run a minimal decision API smoke test:

```bash
python utils/hf_router_decision_example.py
```

### Required Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `BOT_TOKEN` | Telegram bot token from @BotFather | Yes |
| `API_ID` | Telegram API ID from my.telegram.org/apps | Yes |
| `API_HASH` | Telegram API Hash from my.telegram.org/apps | Yes |
| `HUGGINGFACE_TOKEN` | Hugging Face API token for AI moderation | Yes |
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `REDIS_URL` | Redis connection string | Yes |
| `WEBHOOK_URL` | Webhook URL for production | No |
| `WEBHOOK_SECRET` | Secret for webhook verification | No |

---

## Deployment

### Heroku Deployment (One-Click)

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy)

### Manual Heroku Deployment

```bash
# Login to Heroku
heroku login

# Create app
heroku create your-bot-name

# Add PostgreSQL
heroku addons:create heroku-postgresql:essential-0

# Add Redis
heroku addons:create heroku-redis:mini

# Set environment variables
heroku config:set BOT_TOKEN=your_token
heroku config:set API_ID=your_api_id
heroku config:set API_HASH=your_api_hash
heroku config:set HUGGINGFACE_TOKEN=hf_xxxxxYOURKEYxxxxx
heroku config:set WEBHOOK_SECRET=$(openssl rand -hex 32)

# Deploy
git push heroku main

# Scale worker
heroku ps:scale web=1
```

### Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

```bash
# Build and run
docker build -t ai-governor .
docker run -p 8000:8000 --env-file .env ai-governor
```

---

## Configuration

### Group-Level Configuration

Each group can customize:

```python
{
    "language": "en|hi|hinglish",
    "personality_mode": "friendly|strict|corporate|funny|owner",
    "risk_thresholds": {
        "critical": 85,
        "high": 70,
        "medium": 50
    },
    "trust_settings": {
        "auto_restrict_media": 25,
        "auto_ban": 10
    },
    "raid_protection": {
        "join_threshold": 10,
        "time_window": 30,
        "new_account_days": 7
    },
    "engagement": {
        "daily_question_hour": 10,
        "weekly_poll_day": 6,
        "inactive_days_threshold": 7
    }
}
```

### Environment-Specific Settings

See `.env.example` for all available configuration options.

---

## Security

### Security Measures

1. **Input Validation**: All inputs sanitized before processing
2. **Rate Limiting**: AI calls, DB queries, Telegram API calls limited
3. **Admin Verification**: All admin actions verified via Telegram API
4. **Token Encryption**: Sensitive tokens never logged
5. **Webhook Secret**: Webhook endpoints protected
6. **Error Isolation**: Failures don't crash the system

### Privacy

- No message content stored permanently (configurable)
- User data encrypted at rest
- GDPR-compliant data deletion
- No data sharing with third parties

### Compliance

- **GDPR**: Data export and deletion supported
- **COPPA**: No collection of data from users under 13
- **Telegram ToS**: Fully compliant with bot policies

---

## Scaling Strategy

### Horizontal Scaling

```
Load Balancer
    │
    ├──→ Web Dyno 1 (Bot Instance)
    ├──→ Web Dyno 2 (Bot Instance)
    └──→ Web Dyno N (Bot Instance)
            │
            ↓
    ┌───────────────┐
    │   PostgreSQL  │
    │   (Primary)   │
    └───────────────┘
            │
    ┌───────────────┐
    │    Redis      │
    │   (Cache/     │
    │    Queue)     │
    └───────────────┘
```

### Performance Optimizations

1. **Connection Pooling**: Database connections pooled
2. **Async Processing**: All I/O operations async
3. **Caching**: AI results cached for 24 hours
4. **Batch Operations**: Bulk database writes
5. **CDN**: Static assets served via CDN

### Expected Throughput

- **Single Dyno**: 1000 messages/minute
- **3 Dynos**: 3000 messages/minute
- **With Caching**: 5000+ messages/minute

---

## Cost Estimation

### Heroku Costs (Monthly)

| Component | Plan | Cost |
|-----------|------|------|
| Web Dyno | Basic | $7 |
| PostgreSQL | Mini | $5 |
| Redis | Mini | $3 |
| **Total Infrastructure** | | **$15/month** |

### OpenAI API Costs

| Usage Level | Messages/Day | Cost/Month |
|-------------|--------------|------------|
| Small | 1,000 | ~$10 |
| Medium | 10,000 | ~$80 |
| Large | 50,000 | ~$350 |
| Enterprise | 100,000 | ~$650 |

*With caching, actual costs reduced by 60-80%*

### Total Monthly Costs

| Scale | Infrastructure | AI API | Total |
|-------|---------------|--------|-------|
| Starter | $15 | $10 | **$25** |
| Growing | $15 | $80 | **$95** |
| Popular | $30 | $350 | **$380** |
| Enterprise | $100 | $650 | **$750** |

---

## Roadmap

### Phase 1: Core (Completed)
- [x] Basic AI moderation
- [x] Risk scoring engine
- [x] Trust system
- [x] Anti-raid protection
- [x] Control panel

### Phase 2: Enhanced (Q1 2024)
- [ ] Machine learning model training on group-specific data
- [ ] Advanced media analysis (deepfake detection)
- [ ] Voice message transcription and analysis
- [ ] Scheduled message moderation reports
- [ ] Integration with external threat intelligence

### Phase 3: Enterprise (Q2 2024)
- [ ] Multi-bot federation
- [ ] Advanced analytics dashboard
- [ ] Custom rule engine
- [ ] API for external integrations
- [ ] White-label solution

### Phase 4: AI Evolution (Q3 2024)
- [ ] Fine-tuned moderation model
- [ ] Predictive spam detection
- [ ] Conversation context tracking
- [ ] Sentiment trend analysis
- [ ] Automated community health scoring

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Support

- **Documentation**: [docs.ai-governor.com](https://docs.ai-governor.com)
- **Telegram**: [@aghoris](https://t.me/aghoris)
- **Email**: support@ai-governor.com

---

**Built with by the AI Governor Team**

## Heroku dyno scaling (worker-only)

```bash
heroku ps:scale worker=1
heroku ps:scale web=0
```

Recommended runtime config for Heroku ephemeral filesystem:

```bash
heroku config:set CACHE_DIR=/tmp/cache
heroku config:set DATABASE_PATH=/tmp/runtime_state.db
```
