# LiteLLM Proxy Deployment Best Practices

> Compiled from official LiteLLM documentation (2026-03). Production-focused reference.

---

## Table of Contents

1. [Deployment Options](#1-deployment-options)
2. [Configuration Structure](#2-configuration-structure)
3. [Database Setup](#3-database-setup)
4. [Authentication & Key Management](#4-authentication--key-management)
5. [Load Balancing & Routing](#5-load-balancing--routing)
6. [Caching](#6-caching)
7. [Monitoring & Logging](#7-monitoring--logging)
8. [Production Hardening](#8-production-hardening)
9. [Rate Limiting & Budgets](#9-rate-limiting--budgets)
10. [Model Fallback & Retry Strategies](#10-model-fallback--retry-strategies)

---

## 1. Deployment Options

### Minimum Requirements

- **CPU**: 4 vCPU
- **Memory**: 8 GB RAM
- **Redis**: Version 7.0+ (for multi-instance deployments)
- **Database**: PostgreSQL (required for key management, spend tracking)

### Docker (Quick Start)

```bash
docker pull docker.litellm.ai/berriai/litellm:main-stable

docker run \
  -v $(pwd)/litellm_config.yaml:/app/config.yaml \
  -e AZURE_API_KEY=your_key \
  -e AZURE_API_BASE=your_base \
  -p 4000:4000 \
  docker.litellm.ai/berriai/litellm:main-stable \
  --config /app/config.yaml
```

### Docker Compose (Proxy + PostgreSQL + Prometheus)

```bash
curl -O https://raw.githubusercontent.com/BerriAI/litellm/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/BerriAI/litellm/main/prometheus.yml

# Required environment variables
echo 'LITELLM_MASTER_KEY="sk-1234"' > .env
echo 'LITELLM_SALT_KEY="sk-1234"' >> .env
echo 'DATABASE_URL="postgresql://user:pass@host:5432/litellm"' >> .env

docker compose up
```

### Kubernetes Deployment

**ConfigMap:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: litellm-config-file
data:
  config.yaml: |
    model_list:
      - model_name: gpt-4o
        litellm_params:
          model: azure/deployment-name
          api_base: https://endpoint.openai.azure.com/
          api_key: os.environ/AZURE_API_KEY
```

**Deployment with health checks:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: litellm-deployment
spec:
  replicas: 3
  template:
    spec:
      securityContext:
        readOnlyRootFilesystem: true
        runAsNonRoot: true
        runAsUser: 101
        capabilities:
          drop: ["ALL"]
      containers:
      - name: litellm
        image: docker.litellm.ai/berriai/litellm:main-stable
        args:
          - "--port"
          - "4000"
          - "--config"
          - "./proxy_server_config.yaml"
          - "--num_workers"
          - "$(nproc)"
          - "--run_gunicorn"
          - "--max_requests_before_restart"
          - "10000"
        livenessProbe:
          httpGet:
            path: /health/liveliness
            port: 4000
          initialDelaySeconds: 120
        readinessProbe:
          httpGet:
            path: /health/readiness
            port: 4000
          initialDelaySeconds: 120
        volumeMounts:
          - name: ui-volume
            mountPath: /app/var/litellm/ui
          - name: assets-volume
            mountPath: /app/var/litellm/assets
          - name: cache
            mountPath: /app/cache
          - name: migrations
            mountPath: /app/migrations
      volumes:
        - name: ui-volume
          emptyDir: { sizeLimit: 100Mi }
        - name: assets-volume
          emptyDir: { sizeLimit: 10Mi }
        - name: cache
          emptyDir: { sizeLimit: 500Mi }
        - name: migrations
          emptyDir: { sizeLimit: 64Mi }
```

### Helm Chart

```bash
helm pull oci://docker.litellm.ai/berriai/litellm-helm
tar -zxvf litellm-helm-0.1.2.tgz
helm install lite-helm ./litellm-helm
```

### Cloud Platforms

| Platform | Method |
|----------|--------|
| AWS ECS | Terraform module: [litellm-ecs-deployment](https://github.com/BerriAI/litellm-ecs-deployment) |
| AWS EKS | `eksctl create cluster --name=litellm-cluster --region=us-west-2` |
| Google Cloud Run | [Example repo](https://github.com/BerriAI/example_litellm_gcp_cloud_run) |
| Railway | One-click deploy template |

### Config from Cloud Storage

```bash
# S3
export LITELLM_CONFIG_BUCKET_NAME="litellm-proxy"
export LITELLM_CONFIG_BUCKET_OBJECT_KEY="litellm_proxy_config.yaml"

# GCS
export LITELLM_CONFIG_BUCKET_TYPE="gcs"
export LITELLM_CONFIG_BUCKET_NAME="litellm-proxy"
export LITELLM_CONFIG_BUCKET_OBJECT_KEY="proxy_config.yaml"
```

---

## 2. Configuration Structure

The `config.yaml` has five main sections:

```yaml
# 1. Model definitions
model_list:
  - model_name: gpt-4o                    # User-facing name
    litellm_params:
      model: azure/gpt-4o-deployment       # Provider/model identifier
      api_key: os.environ/AZURE_API_KEY     # Reference env vars safely
      api_base: https://endpoint.openai.azure.com/
      rpm: 1000                             # Rate limit for load balancing
      tpm: 100000
    model_info:
      supported_environments: ["production"]

  - model_name: gpt-4o                    # Second deployment (same name = load balanced)
    litellm_params:
      model: openai/gpt-4o
      api_key: os.environ/OPENAI_API_KEY
      rpm: 500
      tpm: 50000

  - model_name: bedrock-embeddings
    litellm_params:
      model: bedrock/amazon.titan-embed-text-v1

# 2. Router settings
router_settings:
  routing_strategy: simple-shuffle         # Recommended default
  redis_host: os.environ/REDIS_HOST
  redis_password: os.environ/REDIS_PASSWORD
  redis_port: os.environ/REDIS_PORT
  num_retries: 3
  timeout: 600
  enable_pre_call_checks: true

# 3. LiteLLM module settings
litellm_settings:
  drop_params: true
  set_verbose: false
  num_retries: 3
  request_timeout: 600
  json_logs: true
  fallbacks: [{"gpt-4o": ["claude-3-sonnet"]}]
  context_window_fallbacks: [{"gpt-3.5-turbo": ["gpt-4-turbo"]}]
  success_callback: ["langfuse"]
  cache: true
  cache_params:
    type: redis
    host: os.environ/REDIS_HOST
    port: os.environ/REDIS_PORT
    password: os.environ/REDIS_PASSWORD

# 4. General server settings
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  alerting: ["slack"]
  proxy_batch_write_at: 60
  database_connection_pool_limit: 10
  database_connection_timeout: 60
  disable_error_logs: true
  allow_requests_on_db_unavailable: true

# 5. Environment variables
environment_variables:
  REDIS_HOST: your-redis-host
  REDIS_PORT: "6379"
```

### Centralized Credentials

```yaml
credential_list:
  - credential_name: azure_production
    credential_values:
      api_key: os.environ/AZURE_API_KEY
      api_base: os.environ/AZURE_API_BASE

model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o
      litellm_credential_name: azure_production
```

### Environment-Based Model Filtering

```bash
export LITELLM_ENVIRONMENT="production"
```

Only models with `supported_environments: ["production"]` will be served.

---

## 3. Database Setup

### PostgreSQL (Required for Production)

```bash
export DATABASE_URL="postgresql://user:password@host:5432/litellm"
export LITELLM_MASTER_KEY="sk-your-master-key"
export LITELLM_SALT_KEY="sk-random-salt-never-change"  # Encryption key, immutable post-deploy
```

**Supported providers:** Supabase, Neon, AWS RDS, any PostgreSQL-compatible DB.

### IAM-Based RDS Authentication

```bash
export AWS_WEB_IDENTITY_TOKEN='/path/to/token'
export DATABASE_USER="db-user"
export DATABASE_HOST="your-rds-host"
litellm --config config.yaml --iam_token_db_auth
```

### Connection Pool Sizing

Formula:
```
pool_limit = MAX_DB_CONNECTIONS / (num_instances * workers_per_instance)
```

Example: 200 max connections, 3 instances, 4 workers each:
```
pool_limit = 200 / (3 * 4) = ~16
```

```yaml
general_settings:
  database_connection_pool_limit: 16
  database_connection_timeout: 60
```

### Database Tables

LiteLLM auto-creates three core tables:
- **LiteLLM_VerificationTokenTable** - API keys and spend
- **LiteLLM_UserTable** - User records and budgets
- **LiteLLM_TeamTable** - Team budgets and membership

### Migration Strategy

```bash
# Use Prisma for safer migrations
export USE_PRISMA_MIGRATE="True"

# Or disable auto-migration for managed deployments
export DISABLE_SCHEMA_UPDATE="true"
```

---

## 4. Authentication & Key Management

### Master Key Setup

```yaml
general_settings:
  master_key: sk-1234  # Must start with "sk-"
```

### Generate Virtual Keys

```bash
curl -X POST 'http://localhost:4000/key/generate' \
  -H 'Authorization: Bearer sk-1234' \
  -H 'Content-Type: application/json' \
  -d '{
    "max_budget": 100,
    "budget_duration": "30d",
    "models": ["gpt-4o", "claude-3-sonnet"],
    "tpm_limit": 50000,
    "rpm_limit": 100,
    "max_parallel_requests": 10
  }'
```

### Team-Based Access Control

```bash
# Create team
curl -X POST 'http://localhost:4000/team/new' \
  -H 'Authorization: Bearer sk-1234' \
  -d '{
    "team_alias": "engineering",
    "max_budget": 500,
    "budget_duration": "30d",
    "tpm_limit": 100000,
    "rpm_limit": 200,
    "members_with_roles": [
      {"role": "admin", "user_id": "admin@company.com"}
    ]
  }'

# Generate key for team
curl -X POST 'http://localhost:4000/key/generate' \
  -H 'Authorization: Bearer sk-1234' \
  -d '{
    "team_id": "team-uuid",
    "max_budget": 50
  }'
```

### Key Lifecycle

- **Block/unblock**: `/key/block`, `/key/unblock`
- **Key rotation** (Enterprise): `/key/sk-1234/regenerate`
- **Scheduled rotation**: `LITELLM_KEY_ROTATION_ENABLED=true`
- **Temp budget increase**: `/key/update` with `temp_budget_increase` and `temp_budget_expiry`

### Custom Auth Header

```yaml
general_settings:
  litellm_key_header_name: "X-Litellm-Key"
```

### Spend Tracking

```bash
# Per key
curl 'http://localhost:4000/key/info?key=sk-xxx'

# Per user
curl 'http://localhost:4000/user/info?user_id=user-123'

# Per team
curl 'http://localhost:4000/team/info?team_id=team-uuid'
```

---

## 5. Load Balancing & Routing

### Routing Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| `simple-shuffle` | Random weighted by RPM/TPM (default) | **Production recommended** |
| `least-busy` | Fewest concurrent requests | Even distribution |
| `usage-based-routing` | Track TPM/RPM usage via Redis | Quota management |
| `latency-based-routing` | Prioritize fastest deployments | Latency-sensitive |
| `cost-based-routing` | Select cheapest healthy deployment | Cost optimization |

> **Warning**: Usage-based routing is NOT recommended for production due to performance impacts. Use `simple-shuffle`.

### Simple-Shuffle with RPM Weights (Recommended)

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o-east
      api_key: os.environ/AZURE_KEY_EAST
      rpm: 900    # Gets ~90% of traffic

  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o-west
      api_key: os.environ/AZURE_KEY_WEST
      rpm: 100    # Gets ~10% of traffic

router_settings:
  routing_strategy: simple-shuffle
  enable_pre_call_checks: true
```

### Priority-Based Routing

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o-primary
      order: 1    # Highest priority

  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o-fallback
      order: 2    # Only used when primary is down

router_settings:
  enable_pre_call_checks: true
```

### Rate-Limit Aware Routing

Requires Redis. Filters out deployments exceeding their TPM/RPM limits:

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o
      tpm: 100000
      rpm: 10000

router_settings:
  routing_strategy: simple-shuffle
  redis_host: os.environ/REDIS_HOST
  redis_password: os.environ/REDIS_PASSWORD
  redis_port: os.environ/REDIS_PORT
  enable_pre_call_checks: true
```

### Max Parallel Requests Per Deployment

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o
      max_parallel_requests: 10
```

### Multi-Instance Redis Coordination

For multiple proxy instances sharing load balancing state:

```yaml
router_settings:
  redis_host: your-redis-host
  redis_password: your-password
  redis_port: 6379

# For 1000+ RPS, enable transaction buffering
general_settings:
  use_redis_transaction_buffer: true
```

---

## 6. Caching

### Supported Cache Types

| Type | Use Case |
|------|----------|
| `redis` | Multi-instance, production |
| `local` | Single instance, development |
| `disk` | Persistent local cache |
| `s3` | Durable cloud storage |
| `gcs` | GCP cloud storage |
| `qdrant-semantic` | Semantic similarity matching |
| `redis-semantic` | Redis-based semantic cache |

### Redis Cache (Recommended for Production)

```yaml
litellm_settings:
  cache: true
  cache_params:
    type: redis
    host: os.environ/REDIS_HOST
    port: os.environ/REDIS_PORT
    password: os.environ/REDIS_PASSWORD
    ttl: 600               # Cache duration in seconds
    max_connections: 100
    namespace: "litellm"   # Key prefix
    supported_call_types: ["acompletion", "aembedding"]
```

### Redis Cluster

```yaml
litellm_settings:
  cache: true
  cache_params:
    type: redis
    redis_startup_nodes:
      - {"host": "127.0.0.1", "port": "7001"}
      - {"host": "127.0.0.1", "port": "7002"}
```

### Redis Sentinel

```yaml
litellm_settings:
  cache: true
  cache_params:
    type: redis
    service_name: "mymaster"
    sentinel_nodes: [["localhost", 26379]]
    sentinel_password: "password"
```

### Semantic Cache (Qdrant)

```yaml
litellm_settings:
  cache: true
  cache_params:
    type: qdrant-semantic
    qdrant_semantic_cache_embedding_model: openai-embedding
    qdrant_collection_name: litellm_cache
    similarity_threshold: 0.8
    qdrant_quantization_config: binary
    qdrant_semantic_cache_vector_size: 1536
```

### Per-Request Cache Controls

```python
from openai import OpenAI
client = OpenAI(api_key="sk-xxx", base_url="http://localhost:4000")

# Set TTL per request
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
    extra_body={"cache": {"ttl": 300}}
)

# Bypass cache
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
    extra_body={"cache": {"no-cache": True}}
)

# Don't store response
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
    extra_body={"cache": {"no-store": True}}
)
```

### Default Cache Off (Opt-In)

```yaml
litellm_settings:
  cache: true
  cache_params:
    mode: default_off
```

Then per request: `extra_body={"cache": {"use-cache": True}}`

### Cache for Rate Limiting Only (No Response Caching)

```yaml
litellm_settings:
  cache: true
  cache_params:
    type: redis
    supported_call_types: []  # Empty = no API caching, but Redis used for rate limiting
```

---

## 7. Monitoring & Logging

### Supported Integrations

**Observability**: Langfuse, OpenTelemetry, Datadog, Lunary, MLflow, Langsmith, Arize AI
**Cloud Storage**: AWS S3, GCS, Azure Blob Storage
**Queues**: AWS SQS, GCP PubSub
**Error Tracking**: Sentry
**Database**: DynamoDB

### Langfuse Setup

```bash
export LANGFUSE_PUBLIC_KEY="pk_xxx"
export LANGFUSE_SECRET_KEY="sk_xxx"
```

```yaml
litellm_settings:
  success_callback: ["langfuse"]
```

Pass metadata for enhanced tracking:
```bash
curl -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-xxx" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}],
    "metadata": {
      "generation_name": "test-gen",
      "trace_id": "trace-22",
      "tags": ["jobID:214590", "taskName:classification"]
    }
  }'
```

### OpenTelemetry

```bash
export OTEL_EXPORTER="otlp_http"
export OTEL_ENDPOINT="https://api.honeycomb.io/v1/traces"
export OTEL_HEADERS="x-honeycomb-team=<api-key>"
```

Distributed tracing via `traceparent` header:
```
traceparent: 00-80e1afed08e019fc1110464cfa66635c-02e80198930058d4-01
```

### AWS S3 Logging

```yaml
litellm_settings:
  callbacks: ["s3_v2"]
  s3_callback_params:
    s3_bucket_name: logs-bucket-litellm
    s3_region_name: us-west-2
    s3_path: litellm-logs/
    s3_use_team_prefix: true
    s3_use_key_prefix: true
```

### Custom Python Callbacks

```python
from litellm.integrations.custom_logger import CustomLogger

class MyCustomHandler(CustomLogger):
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        model = kwargs.get("model")
        cost = litellm.completion_cost(completion_response=response_obj)
        print(f"Model: {model}, Cost: {cost}")

proxy_handler_instance = MyCustomHandler()
```

```yaml
litellm_settings:
  callbacks: custom_callbacks.proxy_handler_instance
```

### Privacy Controls

```yaml
# Redact all messages from logs (keep spend tracking)
litellm_settings:
  turn_off_message_logging: true
```

Per-request: header `x-litellm-enable-message-redaction: true`
Skip logging entirely: `"no-log": true` in request body

### Response Headers (Useful for Debugging)

```
x-litellm-call-id: b980db26-9512-45cc-b1da-c511a363b83f
x-litellm-model-id: cb41bc03f4c33d310019bae8c5afdb1af0a8f97b
x-litellm-response-cost: 2.85e-05
x-litellm-cache-key: 586bf3f3c1bf5aecb...
```

---

## 8. Production Hardening

### Essential Environment Variables

```bash
export LITELLM_MASTER_KEY="sk-your-key"
export LITELLM_SALT_KEY="sk-random-immutable"     # NEVER change post-deploy
export LITELLM_LOG="ERROR"                          # Minimize log noise
export LITELLM_MODE="PRODUCTION"
export LITELLM_LOCAL_MODEL_COST_MAP="True"          # Avoid cold start delays
export SLACK_WEBHOOK_URL="https://hooks.slack.com/..."

# Read-only filesystem support
export LITELLM_MIGRATION_DIR="/path/to/writable/directory"
export LITELLM_UI_PATH="/path/to/writable/directory"
export LITELLM_ASSETS_PATH="/path/to/writable/directory"
export PRISMA_BINARY_CACHE_DIR="/app/cache/prisma-python/binaries"
export XDG_CACHE_HOME="/app/cache"

# Health check separation
export SEPARATE_HEALTH_APP="1"
export SEPARATE_HEALTH_PORT="8001"

# Worker management
export MAX_REQUESTS_BEFORE_RESTART="10000"
export SUPERVISORD_STOPWAITSECS="3600"
```

### Production config.yaml

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o
      api_key: os.environ/AZURE_API_KEY
      api_base: os.environ/AZURE_API_BASE
      rpm: 1000
      tpm: 100000

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  alerting: ["slack"]
  proxy_batch_write_at: 60                   # Batch DB writes every 60s
  database_connection_pool_limit: 10
  disable_error_logs: true                   # Reduce DB writes
  allow_requests_on_db_unavailable: true     # Graceful degradation

litellm_settings:
  request_timeout: 600
  set_verbose: false                         # NEVER true in production
  json_logs: true                            # Structured logging
  num_retries: 3
  cache: true
  cache_params:
    type: redis
    host: os.environ/REDIS_HOST
    port: os.environ/REDIS_PORT
    password: os.environ/REDIS_PASSWORD

router_settings:
  routing_strategy: simple-shuffle           # Best perf, minimal overhead
  redis_host: os.environ/REDIS_HOST
  redis_password: os.environ/REDIS_PASSWORD
  redis_port: os.environ/REDIS_PORT
  enable_pre_call_checks: true
```

### Key Production Rules

1. **Never use `--detailed_debug` in production** -- impacts response times
2. **Never use `set_verbose: true`** -- excessive logging
3. **Use image digests or pinned versions**, not `:main-stable`
4. **Set `LITELLM_SALT_KEY` once and never change it** -- breaks encrypted data
5. **Separate health check app** to prevent load from affecting probes
6. **Worker recycling** with `MAX_REQUESTS_BEFORE_RESTART=10000` to handle memory leaks
7. **Batch DB writes** with `proxy_batch_write_at: 60`
8. **Enable `allow_requests_on_db_unavailable`** for graceful degradation
9. **Run as non-root** (`runAsUser: 101`) with read-only filesystem
10. **Block robots**: `block_robots: true` in config

### SSL/TLS

```bash
docker run docker.litellm.ai/berriai/litellm:main-stable \
  --ssl_keyfile_path path/to/keyfile.key \
  --ssl_certfile_path path/to/certfile.crt
```

### HTTP/2 Support

```dockerfile
RUN pip install hypercorn
# Start with --run_hypercorn flag
```

---

## 9. Rate Limiting & Budgets

### Hierarchy

```
Global Proxy Budget
  -> Team Budget (tpm_limit, rpm_limit, max_budget)
    -> User Budget (within team: max_budget_in_team)
      -> Virtual Key (tpm_limit, rpm_limit, max_budget, max_parallel_requests)
        -> Per-Model Limits (model_rpm_limit, model_tpm_limit)
```

> If a key belongs to a team, team budget applies, not the user's personal budget.
> Rate limits do NOT apply to proxy admin users.

### Global Proxy Budget

```yaml
general_settings:
  max_budget: 10000          # Total proxy spend limit
  budget_duration: "30d"
```

### Team Rate Limits

```bash
curl -X POST 'http://localhost:4000/team/new' \
  -H 'Authorization: Bearer sk-1234' \
  -d '{
    "team_alias": "engineering",
    "max_budget": 500,
    "budget_duration": "30d",
    "tpm_limit": 100000,
    "rpm_limit": 200
  }'
```

### Per-Key Rate Limits

```bash
curl -X POST 'http://localhost:4000/key/generate' \
  -H 'Authorization: Bearer sk-1234' \
  -d '{
    "max_budget": 50,
    "budget_duration": "30d",
    "tpm_limit": 50000,
    "rpm_limit": 100,
    "max_parallel_requests": 10,
    "model_rpm_limit": {"gpt-4o": 50, "claude-3-sonnet": 30},
    "model_tpm_limit": {"gpt-4o": 50000}
  }'
```

### Per-Model Key Budgets (Enterprise)

```bash
curl -X POST 'http://localhost:4000/key/generate' \
  -H 'Authorization: Bearer sk-1234' \
  -d '{
    "model_max_budget": {
      "gpt-4o": {
        "budget_limit": "100.00",
        "time_period": "30d"
      }
    }
  }'
```

### End-User / Customer Budgets

```bash
# Create budget tier
curl -X POST 'http://localhost:4000/budget/new' \
  -H 'Authorization: Bearer sk-1234' \
  -d '{"budget_id": "free-tier", "tpm_limit": 5, "rpm_limit": 10}'

# Assign to customer
curl -X POST 'http://localhost:4000/customer/new' \
  -H 'Authorization: Bearer sk-1234' \
  -d '{"user_id": "end_user_123", "budget_id": "free-tier"}'
```

### Default Budgets for Internal Users

```yaml
litellm_settings:
  max_internal_user_budget: 0              # Default $0 (must explicitly grant)
  internal_user_budget_duration: "1mo"
```

### Budget Duration Formats

`"30s"`, `"30m"`, `"30h"`, `"30d"`, `"1mo"`

Budget resets are checked every 10 minutes. Tune with:
- `proxy_budget_rescheduler_min_time`
- `proxy_budget_rescheduler_max_time`

### Multi-Instance Rate Limit Sync

In-memory cache syncs with Redis every 0.01 seconds for consistent rate limiting across instances.

---

## 10. Model Fallback & Retry Strategies

### Three Fallback Types

1. **Standard Fallbacks** -- general errors (rate limits, 500s)
2. **Content Policy Fallbacks** -- content filtering violations
3. **Context Window Fallbacks** -- input exceeds model capacity

### Complete Reliability Config

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o
      api_key: os.environ/AZURE_API_KEY

  - model_name: claude-3-sonnet
    litellm_params:
      model: anthropic/claude-3-sonnet
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: gpt-4-turbo
    litellm_params:
      model: openai/gpt-4-turbo
      api_key: os.environ/OPENAI_API_KEY

litellm_settings:
  num_retries: 3
  request_timeout: 600
  allowed_fails: 3
  cooldown_time: 30

  # Standard fallbacks
  fallbacks:
    - {"gpt-4o": ["claude-3-sonnet", "gpt-4-turbo"]}

  # Context window overflow
  context_window_fallbacks:
    - {"gpt-3.5-turbo": ["gpt-4-turbo"]}

  # Content policy violations
  content_policy_fallbacks:
    - {"gpt-4o": ["claude-3-sonnet"]}

  # Universal fallback for any unconfigured model
  default_fallbacks: ["claude-3-sonnet"]
```

### Cooldown Configuration

When a deployment exceeds `allowed_fails` failures within 1 minute, it enters cooldown:

```yaml
router_settings:
  allowed_fails: 3
  cooldown_time: 30   # seconds

# Per-model override
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o
      cooldown_time: 0   # Never cooldown this deployment
```

### Advanced Retry Policies

```python
from litellm.router import RetryPolicy, AllowedFailsPolicy

retry_policy = RetryPolicy(
    ContentPolicyViolationErrorRetries=3,
    AuthenticationErrorRetries=0,        # Don't retry auth errors
    BadRequestErrorRetries=1,
    TimeoutErrorRetries=2,
    RateLimitErrorRetries=3,
)

allowed_fails_policy = AllowedFailsPolicy(
    ContentPolicyViolationErrorAllowedFails=1000,
    RateLimitErrorAllowedFails=100,
)
```

### Pre-Call Context Window Validation

Prevent context overflow before making the API call:

```yaml
router_settings:
  enable_pre_call_checks: true

model_list:
  - model_name: gpt-3.5-turbo
    litellm_params:
      model: azure/chatgpt-v-2
    model_info:
      max_input_tokens: 4096
      base_model: azure/gpt-35-turbo
```

### Client-Side Fallback Override

```python
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "test"}],
    extra_body={"fallbacks": ["claude-3-sonnet"]}
)

# Disable fallbacks for specific request
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "test"}],
    extra_body={"disable_fallbacks": True}
)
```

### Testing Fallbacks

```bash
# Test standard fallback
curl -X POST 'http://localhost:4000/chat/completions' \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "test"}], "mock_testing_fallbacks": true}'

# Test content policy fallback
curl -X POST 'http://localhost:4000/chat/completions' \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "test"}], "mock_testing_content_policy_fallbacks": true}'

# Test context window fallback
curl -X POST 'http://localhost:4000/chat/completions' \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "test"}], "mock_testing_context_window_fallbacks": true}'
```

---

## Quick Reference: Production Checklist

- [ ] PostgreSQL database configured with `DATABASE_URL`
- [ ] `LITELLM_MASTER_KEY` set (starts with `sk-`)
- [ ] `LITELLM_SALT_KEY` set (immutable after first deploy)
- [ ] Redis 7.0+ for multi-instance coordination
- [ ] `routing_strategy: simple-shuffle` (not usage-based)
- [ ] `set_verbose: false` and `LITELLM_LOG=ERROR`
- [ ] `json_logs: true` for structured logging
- [ ] Health probes on `/health/liveliness` and `/health/readiness`
- [ ] `SEPARATE_HEALTH_APP=1` for isolated health checks
- [ ] `proxy_batch_write_at: 60` for batched DB writes
- [ ] `allow_requests_on_db_unavailable: true` for graceful degradation
- [ ] `database_connection_pool_limit` calculated per formula
- [ ] Fallbacks configured for critical models
- [ ] `enable_pre_call_checks: true` for context window validation
- [ ] Rate limits set at team and key levels
- [ ] Alerting to Slack configured
- [ ] Logging callbacks configured (Langfuse, OTEL, S3, etc.)
- [ ] Worker recycling: `MAX_REQUESTS_BEFORE_RESTART=10000`
- [ ] Non-root user, read-only filesystem (Kubernetes)
- [ ] Pinned image version (not `:main-stable`)
- [ ] `LITELLM_LOCAL_MODEL_COST_MAP=True` to reduce cold starts
