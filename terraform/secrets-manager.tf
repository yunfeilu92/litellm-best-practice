# ============================================================
# Secrets Manager + ESO (External Secrets Operator) IRSA
# ============================================================

# ---- 生成随机密钥 ----
resource "random_password" "master_key" {
  length  = 32
  special = false
}

resource "random_password" "salt_key" {
  length  = 32
  special = false
}

# ---- Secrets Manager Secret ----
resource "aws_secretsmanager_secret" "litellm" {
  name                    = "${var.project_name}/config"
  description             = "LiteLLM proxy secrets (master key, salt key, DB URL, Redis, AKSK)"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "litellm" {
  secret_id = aws_secretsmanager_secret.litellm.id
  secret_string = jsonencode({
    LITELLM_MASTER_KEY    = "sk-${random_password.master_key.result}"
    LITELLM_SALT_KEY      = "sk-${random_password.salt_key.result}"
    DATABASE_URL           = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.this.endpoint}/${var.db_name}"
    REDIS_HOST             = aws_elasticache_replication_group.this.primary_endpoint_address
    REDIS_PORT             = "6379"
    REDIS_PASSWORD         = ""
    # Bedrock AKSK — 用户手动更新
    AWS_ACCESS_KEY_ID_1     = "CHANGE_ME"
    AWS_SECRET_ACCESS_KEY_1 = "CHANGE_ME"
    AWS_ACCESS_KEY_ID_2     = "CHANGE_ME"
    AWS_SECRET_ACCESS_KEY_2 = "CHANGE_ME"
  })

  lifecycle {
    # salt key 和 master key 生成后不要被意外覆盖
    ignore_changes = [secret_string]
  }
}

# ---- ESO IRSA Role ----
data "aws_iam_policy_document" "eso_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.eks.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(aws_eks_cluster.this.identity[0].oidc[0].issuer, "https://", "")}:sub"
      values   = ["system:serviceaccount:external-secrets:external-secrets"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(aws_eks_cluster.this.identity[0].oidc[0].issuer, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eso" {
  name               = "${var.project_name}-eso"
  assume_role_policy = data.aws_iam_policy_document.eso_assume.json
}

resource "aws_iam_role_policy" "eso" {
  name = "${var.project_name}-eso-secrets-access"
  role = aws_iam_role.eso.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ]
      Resource = [aws_secretsmanager_secret.litellm.arn]
    }]
  })
}

# ---- Outputs ----
output "secrets_manager_secret_name" {
  value = aws_secretsmanager_secret.litellm.name
}

output "eso_role_arn" {
  value = aws_iam_role.eso.arn
}

output "litellm_master_key" {
  value     = "sk-${random_password.master_key.result}"
  sensitive = true
}
