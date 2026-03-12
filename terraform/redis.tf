# ============================================================
# ElastiCache Redis
# ============================================================

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.project_name}-redis"
  subnet_ids = var.private_subnet_ids
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${var.project_name}-redis"
  description          = "LiteLLM Redis for rate limiting and routing state"

  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.redis_node_type
  num_cache_clusters   = 2 # 1 primary + 1 replica (跨 AZ)
  automatic_failover_enabled = true
  multi_az_enabled     = true

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.redis.id]

  port                   = 6379
  transit_encryption_enabled = false # 简化配置，内网通信
  at_rest_encryption_enabled = true

  snapshot_retention_limit = 3
  snapshot_window          = "02:00-03:00"
  maintenance_window       = "sun:03:00-sun:04:00"

  tags = { Name = "${var.project_name}-redis" }
}
