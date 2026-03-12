region       = "us-east-1"
project_name = "litellm"

# Existing VPC
vpc_id = "vpc-00078ff565291bb80"

public_subnet_ids = [
  "subnet-00b66a3945b3c67d3", # poc-subnet-public1-us-east-1a
  "subnet-0b33d7caf63d0243a", # poc-subnet-public2-us-east-1b
]

private_subnet_ids = [
  "subnet-0d0361fd6cbc23dd1", # poc-subnet-private1-us-east-1a
  "subnet-0e12995b749bbe1e7", # poc-subnet-private2-us-east-1b
]

# RDS
db_password = "CHANGE_ME_BEFORE_APPLY" # <-- 部署前必须修改！

# EKS
eks_node_instance_types = ["m6i.xlarge"]
eks_node_desired_size   = 2
