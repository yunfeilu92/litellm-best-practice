variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name prefix for all resources"
  type        = string
  default     = "litellm"
}

# ---- Existing VPC ----
variable "vpc_id" {
  description = "Existing VPC ID"
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet IDs for ALB"
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for EKS nodes, RDS, Redis"
  type        = list(string)
}

# ---- EKS ----
variable "eks_cluster_version" {
  description = "EKS Kubernetes version"
  type        = string
  default     = "1.31"
}

variable "eks_node_instance_types" {
  description = "EC2 instance types for EKS managed node group"
  type        = list(string)
  default     = ["m6i.xlarge"] # 4 vCPU, 16 GB
}

variable "eks_node_desired_size" {
  description = "Desired number of EKS worker nodes"
  type        = number
  default     = 2
}

variable "eks_node_min_size" {
  type    = number
  default = 2
}

variable "eks_node_max_size" {
  type    = number
  default = 4
}

# ---- RDS ----
variable "db_instance_class" {
  type    = string
  default = "db.t3.medium"
}

variable "db_name" {
  type    = string
  default = "litellm"
}

variable "db_username" {
  type    = string
  default = "litellm"
}

variable "db_password" {
  description = "RDS master password"
  type        = string
  sensitive   = true
}

# ---- Redis ----
variable "redis_node_type" {
  type    = string
  default = "cache.t3.medium"
}
