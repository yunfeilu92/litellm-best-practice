# ============================================================
# Outputs
# ============================================================

# ---- EKS ----
output "eks_cluster_name" {
  value = aws_eks_cluster.this.name
}

output "eks_cluster_endpoint" {
  value = aws_eks_cluster.this.endpoint
}

output "eks_update_kubeconfig_command" {
  value = "aws eks update-kubeconfig --name ${aws_eks_cluster.this.name} --region ${var.region}"
}

# ---- RDS ----
output "rds_endpoint" {
  value = aws_db_instance.this.endpoint
}

output "database_url" {
  value     = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.this.endpoint}/${var.db_name}"
  sensitive = true
}

# ---- Redis ----
output "redis_endpoint" {
  value = aws_elasticache_replication_group.this.primary_endpoint_address
}

# ---- S3 ----
output "log_bucket_name" {
  value = aws_s3_bucket.logs.bucket
}

# ---- ALB Controller ----
output "lb_controller_role_arn" {
  value = aws_iam_role.lb_controller.arn
}

# ---- 部署后下一步 ----
output "next_steps" {
  value = <<-EOT

    ========== 部署完成后操作 ==========

    1. 更新 kubeconfig:
       aws eks update-kubeconfig --name ${aws_eks_cluster.this.name} --region ${var.region}

    2. 安装 External Secrets Operator:
       helm repo add external-secrets https://charts.external-secrets.io
       helm install external-secrets external-secrets/external-secrets \
         -n external-secrets --create-namespace \
         --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=${aws_iam_role.eso.arn}

    3. 安装 AWS Load Balancer Controller:
       helm repo add eks https://aws.github.io/eks-charts
       helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
         -n kube-system \
         --set clusterName=${aws_eks_cluster.this.name} \
         --set serviceAccount.create=true \
         --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=${aws_iam_role.lb_controller.arn}

    4. 更新 Bedrock AKSK 到 Secrets Manager:
       aws secretsmanager get-secret-value --secret-id ${aws_secretsmanager_secret.litellm.name} --query SecretString --output text | jq .
       # 用 aws secretsmanager update-secret 更新 AKSK 字段

    5. 部署 LiteLLM:
       kubectl apply -f k8s/

    6. 获取 ALB 地址:
       kubectl get ingress -n litellm
  EOT
}
