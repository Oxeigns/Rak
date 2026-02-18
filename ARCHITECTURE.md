# AI Governor Bot - Architecture Documentation

## System Overview

AI Governor is built on a **layered microservices architecture** with clear separation of concerns, enabling horizontal scalability and maintainability.

---

## Architecture Layers

### 1. Presentation Layer
**Components:**
- Telegram Bot API Interface (python-telegram-bot)
- Webhook Endpoint (FastAPI)
- Control Panel UI (Inline Keyboards)

**Responsibilities:**
- Receive and parse Telegram updates
- Send responses and notifications
- Handle admin interactions
- Render inline UIs

### 2. Application Layer
**Components:**
- Message Processor
- Command Handlers
- Callback Handlers
- Event Coordinators

**Responsibilities:**
- Orchestrate message flow
- Route events to appropriate handlers
- Manage conversation state
- Enforce access control

### 3. Domain Layer
**Components:**
- Risk Scoring Engine
- AI Moderation Service
- Trust Engine
- Anti-Raid System
- Engagement Engine
- Control Panel Service

**Responsibilities:**
- Core business logic
- Mathematical calculations
- AI/ML operations
- Behavioral analysis

### 4. Infrastructure Layer
**Components:**
- Database Manager (SQLAlchemy/AsyncPG)
- Cache Manager (Redis)
- AI API Client
- Security Services

**Responsibilities:**
- Data persistence
- Caching
- External API communication
- Security enforcement

---

## Data Flow Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         DATA FLOW                                  │
└────────────────────────────────────────────────────────────────────┘

Telegram Update
      │
      ▼
┌─────────────┐
│  Webhook    │────┐
│  Receiver   │    │
└─────────────┘    │
                   ▼
            ┌─────────────┐
            │  Message    │
            │  Parser     │
            └─────────────┘
                   │
      ┌────────────┼────────────┐
      │            │            │
      ▼            ▼            ▼
┌─────────┐ ┌──────────┐ ┌──────────┐
│Pre-     │ │  User    │ │  Group   │
│Processor│ │  Context │ │ Settings │
└────┬────┘ └────┬─────┘ └────┬─────┘
     │           │            │
     └───────────┴────────────┘
                 │
                 ▼
        ┌─────────────────┐
        │  AI Analysis    │◄────── OpenAI API
        │  Pipeline       │
        └────────┬────────┘
                 │
                 ▼
        ┌─────────────────┐
        │  Risk Engine    │◄────── Mathematical
        │  Calculation    │        Computation
        └────────┬────────┘
                 │
                 ▼
        ┌─────────────────┐
        │  Decision       │
        │  Engine         │
        └────────┬────────┘
                 │
      ┌──────────┼──────────┐
      │          │          │
      ▼          ▼          ▼
┌─────────┐ ┌────────┐ ┌─────────┐
│ Action  │ │ Trust  │ │  Log    │
│Executor │ │ Update │ │ Events  │
└────┬────┘ └───┬────┘ └────┬────┘
     │          │           │
     │    ┌─────┘           │
     │    │                 │
     ▼    ▼                 ▼
┌──────────────────────────────────┐
│          DATABASE                │
│  (PostgreSQL + Redis Cache)      │
└──────────────────────────────────┘
```

---

## Risk Scoring Algorithm (Detailed)

### Step 1: Factor Collection
```python
factors = {
    "spam": 0.0 to 1.0,      # From AI analysis
    "toxic": 0.0 to 1.0,     # From AI analysis
    "scam": 0.0 to 1.0,      # From AI analysis
    "illegal": 0.0 to 1.0,   # From AI analysis
    "phishing": 0.0 to 1.0,  # From AI analysis
    "nsfw": 0.0 to 1.0,      # From AI analysis
    "flood": 0.0 to 1.0,     # From rate calculation
    "user_history": 0.0 to 1.0,  # From trust score
    "similarity": 0.0 to 1.0,    # From duplicate detection
    "link_suspicious": 0.0 to 1.0,  # From link analysis
}
```

### Step 2: Weighted Calculation
```python
# Formula: R = 1 - ∏(1 - Wi × Si)
# This is equivalent to the probability of at least one event occurring

product = 1.0
for weight, score in factor_weights:
    product *= (1 - weight * score)

risk_score = 1 - product
```

### Step 3: Dynamic Escalation
```python
# Base risk score from factors
base_risk = 0.65

# Apply escalations
escalation = 1.0

# Recent violations escalation
if violations_24h > 3:
    escalation *= 1.15  # +15%

# Low trust escalation
if trust_score < 20:
    escalation *= 1.25  # +25%

escalated_risk = min(base_risk * escalation, 1.0)
```

### Step 4: Sigmoid Smoothing
```python
# Apply sigmoid to normalize distribution
# This prevents extreme scores and creates a smoother curve

smoothed_risk = 1 / (1 + exp(-k * (escalated_risk - 0.5)))
# Where k = 10 for steepness
```

### Step 5: Final Scaling
```python
final_score = smoothed_risk * 100  # Scale to 0-100
```

---

## Database Schema (Entity-Relationship)

```
┌────────────────────────────────────────────────────────────────────┐
│                         ENTITY RELATIONSHIPS                       │
└────────────────────────────────────────────────────────────────────┘

┌─────────────┐       ┌──────────────┐       ┌─────────────────┐
│    User     │───────│  GroupUser   │───────│     Group       │
│  (Global)   │  1:M  │  (Membership)│  M:1   │   (Per-Group)   │
└─────────────┘       └──────────────┘       └─────────────────┘
      │                       │                        │
      │                       │                        │
      ▼                       ▼                        ▼
┌─────────────┐       ┌──────────────┐       ┌─────────────────┐
│   Message   │       │  Violation   │       │  GroupSettings  │
│             │       │              │       │                 │
└─────────────┘       └──────────────┘       └─────────────────┘

Additional Entities:
- RaidEvent (Tracks raid attempts)
- EngagementLog (Tracks engagement activities)
- AIAnalysisCache (Caches AI results)
- SystemLog (Audit trail)

Relationships:
- User 1:M Message
- User 1:M Violation
- Group 1:M Message
- Group 1:M Violation
- Group 1:1 GroupSettings
- Group 1:M RaidEvent
- Group 1:M EngagementLog
```

---

## Caching Strategy

### Multi-Level Cache Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         CACHE LAYERS                               │
└────────────────────────────────────────────────────────────────────┘

Level 1: In-Memory (Application)
├── Risk calculation intermediate results
├── Active user sessions
└── Control panel states
TTL: 5-15 minutes

Level 2: Redis (Shared)
├── AI analysis results
├── User trust scores
├── Recent message hashes
├── Raid detection events
└── Rate limiting counters
TTL: 1-24 hours

Level 3: PostgreSQL (Persistent)
├── All entity data
├── Historical violations
├── Audit logs
└── Configuration settings
TTL: Permanent
```

### Cache Invalidation Strategy

```python
# Time-based invalidation
AI_CACHE_TTL = timedelta(hours=24)
TRUST_CACHE_TTL = timedelta(minutes=15)

# Event-based invalidation
- On violation: Invalidate user trust cache
- On settings change: Invalidate group config cache
- On ban: Invalidate user session cache
```

---

## Async Architecture

### Concurrency Model

```python
# All I/O operations are async
async def process_message(message):
    # Concurrent independent operations
    ai_task = analyze_with_ai(message.text)
    user_task = get_user_history(message.from_user.id)
    group_task = get_group_settings(message.chat.id)
    
    # Gather results concurrently
    ai_result, user_history, group_settings = await asyncio.gather(
        ai_task, user_task, group_task
    )
    
    # Sequential dependent operations
    risk = await calculate_risk(ai_result, user_history)
    action = await determine_action(risk, group_settings)
    await execute_action(action)
```

### Connection Pooling

```python
# Database pool
DB_POOL_SIZE = 20
DB_MAX_OVERFLOW = 10

# Redis pool
REDIS_POOL_SIZE = 10

# HTTP client pool
HTTP_POOL_SIZE = 100
```

---

## Error Handling & Resilience

### Error Isolation

```python
class ModerationPipeline:
    async def process(self, message):
        try:
            # Preprocessing (never fails)
            normalized = self.preprocess(message)
        except Exception as e:
            logger.error(f"Preprocessing failed: {e}")
            normalized = message.text
        
        try:
            # AI Analysis (has fallback)
            analysis = await self.ai_analyze(normalized)
        except AIError:
            # Fallback to rule-based
            analysis = self.rule_based_analysis(normalized)
        
        try:
            # Risk calculation (critical)
            risk = self.calculate_risk(analysis)
        except Exception as e:
            logger.critical(f"Risk calculation failed: {e}")
            # Fail-safe: allow message
            return Action.ALLOW
```

### Circuit Breaker Pattern

```python
class AICircuitBreaker:
    def __init__(self):
        self.failures = 0
        self.threshold = 5
        self.timeout = 60
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    async def call(self, func, *args):
        if self.state == "OPEN":
            if time() - self.last_failure > self.timeout:
                self.state = "HALF_OPEN"
            else:
                raise CircuitOpenError()
        
        try:
            result = await func(*args)
            self.on_success()
            return result
        except Exception as e:
            self.on_failure()
            raise e
```

---

## Security Architecture

### Defense Layers

```
Layer 1: Network
├── HTTPS only
├── Webhook secret verification
└── IP rate limiting

Layer 2: Application
├── Input sanitization
├── SQL injection prevention (parameterized queries)
├── XSS prevention (output encoding)
└── CSRF protection

Layer 3: Data
├── Encryption at rest (PostgreSQL native)
├── Encrypted connections (SSL/TLS)
├── No sensitive data in logs
└── Principle of least privilege

Layer 4: Access
├── Admin verification via Telegram API
├── Permission checks on all actions
├── Audit logging
└── Session management
```

---

## Deployment Architecture

### Heroku Deployment

```
┌────────────────────────────────────────────────────────────────────┐
│                         HEROKU SETUP                               │
└────────────────────────────────────────────────────────────────────┘

Web Dyno (FastAPI)
│   ├── Gunicorn workers (4)
│   └── Uvicorn async server
│
├── Heroku PostgreSQL
│   ├── Primary database
│   └── Automated backups
│
├── Heroku Redis
│   ├── Session cache
│   └── AI result cache
│
└── Add-ons
    ├── LogDNA (logging)
    ├── Papertrail (log aggregation)
    └── New Relic (APM)
```

### Environment Configuration

```python
# Development
DEBUG = True
WEBHOOK_URL = None  # Use polling
LOG_LEVEL = "DEBUG"

# Staging
DEBUG = False
WEBHOOK_URL = "https://staging.example.com/webhook"
LOG_LEVEL = "INFO"

# Production
DEBUG = False
WEBHOOK_URL = "https://api.example.com/webhook"
LOG_LEVEL = "WARNING"
SENTRY_DSN = "https://..."
METRICS_ENABLED = True
```

---

## Monitoring & Observability

### Metrics Collection

```python
# Application metrics
- Messages processed per minute
- Average risk score
- AI API latency
- Database query time
- Cache hit rate

# Business metrics
- Violations detected
- False positive rate
- User trust score distribution
- Raid attempts blocked
- Engagement activity
```

### Logging Strategy

```python
# Structured logging
{
    "timestamp": "2024-01-15T10:30:00Z",
    "level": "INFO",
    "component": "risk_engine",
    "event": "risk_calculated",
    "data": {
        "user_id": 123456,
        "group_id": 789012,
        "risk_score": 75.5,
        "action": "warn"
    }
}
```

---

## Performance Characteristics

### Latency Budgets

| Operation | Target | Max |
|-----------|--------|-----|
| Message processing | < 500ms | 2000ms |
| AI analysis (cached) | < 10ms | 50ms |
| AI analysis (API) | < 2000ms | 5000ms |
| Risk calculation | < 50ms | 100ms |
| Database query | < 20ms | 100ms |
| Total response | < 3000ms | 5000ms |

### Throughput

| Metric | Single Instance | 3 Instances | 10 Instances |
|--------|----------------|-------------|--------------|
| Messages/sec | 50 | 150 | 500 |
| Concurrent users | 1000 | 3000 | 10000 |
| AI calls/min | 100 | 300 | 1000 |

---

## Future Architecture Evolution

### Phase 2: ML Model Serving

```
┌────────────────────────────────────────────────────────────────────┐
│                     ML MODEL SERVING                               │
└────────────────────────────────────────────────────────────────────┘

Current: OpenAI API
         ↓
Future:  Custom ML Model
         ├── TensorFlow Serving
         ├── Fine-tuned on group data
         └── Lower latency, higher accuracy
```

### Phase 3: Distributed Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                     DISTRIBUTED SETUP                              │
└────────────────────────────────────────────────────────────────────┘

Load Balancer (Nginx/CloudFlare)
    │
    ├──→ Web Dyno 1 (US-East)
    ├──→ Web Dyno 2 (US-West)
    ├──→ Web Dyno 3 (EU-West)
    └──→ Web Dyno 4 (Asia)
            │
            ↓
    ┌───────────────────┐
    │  Global Database  │ (CockroachDB/Spanner)
    │  (Multi-region)   │
    └───────────────────┘
```

---

**Document Version:** 2.0.0  
**Last Updated:** 2024-01-15  
**Author:** AI Governor Architecture Team
