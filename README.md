# LiteLLM 部署最佳实践：Claude Code / OpenClaw + AWS Bedrock

> 场景：用 LiteLLM Proxy 统一网关，对接 AWS Bedrock（Claude 模型），为 Claude Code 和 OpenClaw 等 AI 编程工具提供 OpenAI 兼容 API，支持 API Key 级别的 quota 控制和高可用。

---

## 架构概览

```
┌─────────────┐  ┌─────────────┐
│ Claude Code  │  │  OpenClaw   │
└──────┬───────┘  └──────┬──────┘
       │ OpenAI API       │
       └────────┬─────────┘
                ▼
        ┌───────────────┐
        │   ALB / NLB   │
        └───────┬───────┘
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
┌────────┐ ┌────────┐ ┌────────┐
│LiteLLM │ │LiteLLM │ │LiteLLM │  ← 多实例（ECS/EKS）
│  #1    │ │  #2    │ │  #3    │
└───┬────┘ └───┬────┘ └───┬────┘
    │          │          │
    ├──────────┼──────────┤
    ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐
│ Redis  │ │Postgres│ │  S3    │
│(HA)    │ │(RDS)   │ │(Logs)  │
└────────┘ └────────┘ └────────┘
    │
    └──── Rate Limit 同步
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
┌────────────┐┌────────────┐┌────────────┐
│ Bedrock    ││ Bedrock    ││ Bedrock    │
│ us-east-1  ││ us-west-2  ││ eu-west-1  │  ← 多 Region HA
│ (AKSK-1)   ││ (AKSK-2)   ││ (AKSK-3)   │
└────────────┘└────────────┘└────────────┘
```

---

## 1. 核心配置：config.yaml

```yaml
# ============================================================
# LiteLLM Proxy Config - Claude Code / OpenClaw + AWS Bedrock
# ============================================================

# ---- Model 定义 ----
# 同一个 model_name 配置多个 deployment = 自动负载均衡 + 故障转移
model_list:
  # Claude Sonnet 4.6 - 主力模型（cross-region inference）
  - model_name: claude-sonnet-4-6-20250514
    litellm_params:
      model: bedrock/us.anthropic.claude-sonnet-4-6
      aws_access_key_id: os.environ/AWS_ACCESS_KEY_ID_1
      aws_secret_access_key: os.environ/AWS_SECRET_ACCESS_KEY_1
      aws_region_name: us-east-1
      rpm: 100
      tpm: 400000
      max_parallel_requests: 20

  # 别名：Claude Code 会用这个短名请求
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: bedrock/us.anthropic.claude-sonnet-4-6
      aws_access_key_id: os.environ/AWS_ACCESS_KEY_ID_1
      aws_secret_access_key: os.environ/AWS_SECRET_ACCESS_KEY_1
      aws_region_name: us-east-1
      rpm: 100
      tpm: 400000
      max_parallel_requests: 20

  # Claude Opus 4.6 - 高级模型
  - model_name: claude-opus-4-6-20250514
    litellm_params:
      model: bedrock/us.anthropic.claude-opus-4-6-v1
      aws_access_key_id: os.environ/AWS_ACCESS_KEY_ID_1
      aws_secret_access_key: os.environ/AWS_SECRET_ACCESS_KEY_1
      aws_region_name: us-east-1
      rpm: 50
      tpm: 200000
      max_parallel_requests: 10

  # 别名：Claude Code 会用这个短名请求
  - model_name: claude-opus-4-6
    litellm_params:
      model: bedrock/us.anthropic.claude-opus-4-6-v1
      aws_access_key_id: os.environ/AWS_ACCESS_KEY_ID_1
      aws_secret_access_key: os.environ/AWS_SECRET_ACCESS_KEY_1
      aws_region_name: us-east-1
      rpm: 50
      tpm: 200000
      max_parallel_requests: 10

  # Claude Haiku 3.5 - 轻量模型（降级/成本控制）
  - model_name: claude-haiku-3.5
    litellm_params:
      model: bedrock/us.anthropic.claude-3-5-haiku-20241022-v1:0
      aws_access_key_id: os.environ/AWS_ACCESS_KEY_ID_1
      aws_secret_access_key: os.environ/AWS_SECRET_ACCESS_KEY_1
      aws_region_name: us-east-1
      rpm: 200
      tpm: 800000
      max_parallel_requests: 50

# ---- 路由设置 ----
router_settings:
  routing_strategy: simple-shuffle        # 生产推荐，基于 RPM 权重随机分发
  redis_host: os.environ/REDIS_HOST
  redis_password: os.environ/REDIS_PASSWORD
  redis_port: os.environ/REDIS_PORT
  num_retries: 3
  timeout: 600                            # Claude Code 长对话需要较长超时
  enable_pre_call_checks: true            # 请求前校验 context window
  allowed_fails: 3
  cooldown_time: 30                       # 故障 deployment 冷却 30s

# ---- LiteLLM 设置 ----
litellm_settings:
  drop_params: true                       # 自动丢弃 provider 不支持的参数
  set_verbose: false                      # 生产环境必须 false
  num_retries: 3
  request_timeout: 600
  json_logs: true

  # Fallback 策略：Sonnet 失败 → 换 Region 的 Sonnet（已通过多 deployment 自动处理）
  # 跨模型 Fallback（可选）
  fallbacks:
    - {"claude-sonnet-4-6": ["claude-haiku-3.5"]}
    - {"claude-sonnet-4-6-20250514": ["claude-haiku-3.5"]}

  # 缓存 - 仅用于 rate limiting，不缓存 LLM 响应（编程场景每次结果不同）
  cache: true
  cache_params:
    type: redis
    host: os.environ/REDIS_HOST
    port: os.environ/REDIS_PORT
    password: os.environ/REDIS_PASSWORD
    supported_call_types: []              # 空 = 不缓存响应，Redis 仅用于 rate limit 同步

  # 日志
  success_callback: ["s3"]
  s3_callback_params:
    s3_bucket_name: os.environ/LOG_BUCKET_NAME
    s3_region_name: os.environ/LOG_BUCKET_REGION
    s3_path: "litellm-logs/"
    s3_use_team_prefix: true
    s3_use_key_prefix: true

# ---- 全局设置 ----
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  alerting: ["slack"]
  proxy_batch_write_at: 60                # 每 60s 批量写 DB，减轻压力
  database_connection_pool_limit: 10
  database_connection_timeout: 60
  disable_error_logs: true
  allow_requests_on_db_unavailable: true  # DB 挂了也能继续服务
```

---

## 2. API Key Quota 管理

### 2.1 为每个用户/团队生成带配额的 Key

```bash
# 创建团队
curl -X POST 'http://litellm:4000/team/new' \
  -H 'Authorization: Bearer $LITELLM_MASTER_KEY' \
  -H 'Content-Type: application/json' \
  -d '{
    "team_alias": "dev-team-alice",
    "max_budget": 200,
    "budget_duration": "1mo",
    "tpm_limit": 200000,
    "rpm_limit": 100,
    "models": ["claude-sonnet-4-6", "claude-haiku-3.5"]
  }'

# 为用户生成 Key（限制预算 + 速率）
curl -X POST 'http://litellm:4000/key/generate' \
  -H 'Authorization: Bearer $LITELLM_MASTER_KEY' \
  -H 'Content-Type: application/json' \
  -d '{
    "team_id": "<team-uuid>",
    "key_alias": "alice-claude-code",
    "max_budget": 50,
    "budget_duration": "1mo",
    "tpm_limit": 100000,
    "rpm_limit": 60,
    "max_parallel_requests": 5,
    "models": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-3.5"],
    "metadata": {"user": "alice", "tool": "claude-code"}
  }'
```

### 2.2 Quota 层级

```
全局 Proxy Budget ($10000/月)
  └── Team Budget ($200/月, 200K TPM)
       └── API Key Budget ($50/月, 100K TPM, 60 RPM, 5 并发)
            └── Per-Model 限制（可选，Enterprise 功能）
```

### 2.3 查询用量

```bash
# 查询 Key 用量
curl 'http://litellm:4000/key/info?key=sk-xxx' \
  -H 'Authorization: Bearer $LITELLM_MASTER_KEY'

# 查询 Team 用量
curl 'http://litellm:4000/team/info?team_id=<team-uuid>' \
  -H 'Authorization: Bearer $LITELLM_MASTER_KEY'
```

### 2.4 Claude Code 客户端配置

```bash
# 环境变量方式（推荐）
export ANTHROPIC_BASE_URL="http://<your-alb-address>"
export ANTHROPIC_API_KEY="sk-your-litellm-virtual-key"
claude

# 注意：
# - Virtual Key 必须包含 claude-sonnet-4-6 和 claude-opus-4-6 模型权限
# - ANTHROPIC_BASE_URL 不要有尾部斜杠
# - 如果同时设置了 ANTHROPIC_AUTH_TOKEN，需要先 unset
```

---

## 3. 高可用方案

### 3.1 LiteLLM 实例高可用

| 层级 | 方案 | 说明 |
|------|------|------|
| **负载均衡** | ALB/NLB | 前端 LB 分发到多个 LiteLLM 实例 |
| **实例** | ECS Service / K8s Deployment | ≥2 副本，跨 AZ 部署 |
| **健康检查** | `/health/liveliness` + `/health/readiness` | 分离健康检查端口 (`SEPARATE_HEALTH_APP=1`) |
| **Worker 回收** | `MAX_REQUESTS_BEFORE_RESTART=10000` | 防止内存泄漏 |
| **DB 降级** | `allow_requests_on_db_unavailable: true` | DB 故障时继续服务（quota 暂不检查） |

**ECS 部署示例（docker-compose 风格）：**

```yaml
services:
  litellm:
    image: docker.litellm.ai/berriai/litellm:v1.x.x  # 固定版本号！
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '4'
          memory: 8G
    ports:
      - "4000:4000"
    environment:
      - LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY}
      - LITELLM_SALT_KEY=${LITELLM_SALT_KEY}
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_HOST=${REDIS_HOST}
      - REDIS_PORT=6379
      - REDIS_PASSWORD=${REDIS_PASSWORD}
      - AWS_ACCESS_KEY_ID_1=${AWS_ACCESS_KEY_ID_1}
      - AWS_SECRET_ACCESS_KEY_1=${AWS_SECRET_ACCESS_KEY_1}
      - AWS_ACCESS_KEY_ID_2=${AWS_ACCESS_KEY_ID_2}
      - AWS_SECRET_ACCESS_KEY_2=${AWS_SECRET_ACCESS_KEY_2}
      - LITELLM_LOG=ERROR
      - LITELLM_LOCAL_MODEL_COST_MAP=True
      - SEPARATE_HEALTH_APP=1
      - SEPARATE_HEALTH_PORT=8001
      - MAX_REQUESTS_BEFORE_RESTART=10000
    command: >
      --config /app/config.yaml
      --port 4000
      --num_workers 4
      --run_gunicorn
    volumes:
      - ./config.yaml:/app/config.yaml:ro
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health/liveliness"]
      interval: 30s
      timeout: 10s
      retries: 3

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    deploy:
      resources:
        limits:
          memory: 1G

  # PostgreSQL 建议使用 RDS，这里仅供本地测试
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: litellm
      POSTGRES_USER: litellm
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

### 3.2 后端 Bedrock API Key 高可用

**策略：多 Account / 多 Region 的 AKSK 分散风险**

```
                    ┌─── Account A, us-east-1 (AKSK-1) ───→ Bedrock
                    │
LiteLLM Router ─────┼─── Account A, us-west-2 (AKSK-2) ───→ Bedrock
(simple-shuffle)    │
                    └─── Account B, us-east-1 (AKSK-3) ───→ Bedrock
```

**为什么多 Account？**
- 单 Account 有 Bedrock 并发限制（Service Quota）
- 不同 Account 的 quota 独立
- 一个 Account 的 AKSK 泄露/被禁不影响其他

**配置多 AKSK：**

```yaml
model_list:
  # Account A - us-east-1
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: bedrock/us.anthropic.claude-sonnet-4-6
      aws_access_key_id: os.environ/ACCT_A_AK
      aws_secret_access_key: os.environ/ACCT_A_SK
      aws_region_name: us-east-1
      rpm: 100
      tpm: 400000

  # Account A - us-west-2
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: bedrock/us.anthropic.claude-sonnet-4-6
      aws_access_key_id: os.environ/ACCT_A_AK
      aws_secret_access_key: os.environ/ACCT_A_SK
      aws_region_name: us-west-2
      rpm: 100
      tpm: 400000

  # Account B - us-east-1（不同 AKSK）
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: bedrock/us.anthropic.claude-sonnet-4-6
      aws_access_key_id: os.environ/ACCT_B_AK
      aws_secret_access_key: os.environ/ACCT_B_SK
      aws_region_name: us-east-1
      rpm: 100
      tpm: 400000
```

**Bedrock AKSK 安全最佳实践：**
- 使用 IAM Role 而非长期 AKSK（ECS Task Role / EKS IRSA）
- 如果必须用 AKSK，存放在 AWS Secrets Manager，通过 ECS Secret 注入
- 定期轮换 Key
- 最小权限原则：只授予 `bedrock:InvokeModel` 和 `bedrock:InvokeModelWithResponseStream`

### 3.3 依赖组件高可用

| 组件 | 推荐方案 |
|------|---------|
| **PostgreSQL** | RDS Multi-AZ（自动故障转移） |
| **Redis** | ElastiCache Redis（Cluster Mode 或 Replica） |
| **日志存储** | S3（天然高可用） |

---

## 4. 环境变量清单

```bash
# ---- 必需 ----
LITELLM_MASTER_KEY="sk-your-master-key"        # 管理密钥
LITELLM_SALT_KEY="sk-random-salt-never-change"  # 加密盐，部署后不可更改！
DATABASE_URL="postgresql://user:pass@rds-host:5432/litellm"

# ---- Redis ----
REDIS_HOST="your-elasticache-host"
REDIS_PORT="6379"
REDIS_PASSWORD="your-redis-password"

# ---- AWS Bedrock (多 Account/Region) ----
# 推荐用 IAM Role 替代，以下仅作参考
AWS_ACCESS_KEY_ID_1="AKIA..."
AWS_SECRET_ACCESS_KEY_1="..."
AWS_ACCESS_KEY_ID_2="AKIA..."
AWS_SECRET_ACCESS_KEY_2="..."

# 如果用 IAM Role（推荐），无需以上 AKSK，Bedrock SDK 会自动获取

# ---- 运维 ----
LITELLM_LOG="ERROR"
LITELLM_LOCAL_MODEL_COST_MAP="True"
SEPARATE_HEALTH_APP="1"
SEPARATE_HEALTH_PORT="8001"
MAX_REQUESTS_BEFORE_RESTART="10000"
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# ---- 日志 ----
LOG_BUCKET_NAME="your-litellm-logs-bucket"
LOG_BUCKET_REGION="us-east-1"
```

---

## 5. 运维 Checklist

### 部署前
- [ ] PostgreSQL (RDS Multi-AZ) 就绪
- [ ] Redis (ElastiCache) 就绪
- [ ] `LITELLM_SALT_KEY` 已设置并安全保存（永不可变）
- [ ] `LITELLM_MASTER_KEY` 已设置
- [ ] Bedrock Model Access 已在目标 Region/Account 开通
- [ ] IAM Policy 只授予 `bedrock:InvokeModel*`
- [ ] LiteLLM 镜像使用固定版本号

### 部署后
- [ ] `/health/readiness` 返回 200
- [ ] Master Key 可调用 `/model/info` 验证模型列表
- [ ] 生成测试 Virtual Key 并验证 quota 生效
- [ ] 用 Claude Code 连接并测试完整对话
- [ ] Slack 告警收到测试通知
- [ ] S3 日志桶有写入

### 日常运维
- [ ] 监控 Key 用量：`/key/info`
- [ ] 监控 Team 用量：`/team/info`
- [ ] 定期审计未使用的 Key：`/key/block`
- [ ] Bedrock Service Quota 监控（CloudWatch）
- [ ] Redis / PostgreSQL 连接数监控

---

## 6. 常见问题

### Q: Claude Code 怎么配置连接 LiteLLM？

最简单的方式是设置环境变量：
```bash
export ANTHROPIC_BASE_URL="https://your-litellm-proxy.example.com"
export ANTHROPIC_API_KEY="sk-your-litellm-virtual-key"
```

### Q: Bedrock 用 IAM Role 还是 AKSK？

**强烈推荐 IAM Role：**
- ECS → Task Role
- EKS → IRSA (IAM Roles for Service Accounts)
- EC2 → Instance Profile

LiteLLM 支持自动从环境获取 credentials，无需在 config 中写 AKSK：
```yaml
model_list:
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: bedrock/us.anthropic.claude-sonnet-4-6
      aws_region_name: us-east-1
      # 不写 aws_access_key_id / aws_secret_access_key
      # LiteLLM 会自动使用 boto3 默认 credential chain
```

### Q: 需要对接多少个 Bedrock Region/Account？

建议至少 **2 个 Region**（同 Account），如果流量大则 **2+ Account × 2+ Region**。根据 Bedrock Service Quota 决定。

### Q: Rate Limit 怎么跨多个 LiteLLM 实例同步？

通过 Redis。配置 `router_settings.redis_host` 后，所有实例每 0.01s 同步一次 rate limit 状态。

### Q: budget 超了会怎样？

返回 HTTP 429，response body 包含超限信息。Claude Code 会收到错误提示。
