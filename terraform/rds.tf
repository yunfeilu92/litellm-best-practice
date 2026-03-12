# ============================================================
# RDS PostgreSQL (Multi-AZ)
# ============================================================

resource "aws_db_subnet_group" "this" {
  name       = "${var.project_name}-db"
  subnet_ids = var.private_subnet_ids

  tags = { Name = "${var.project_name}-db" }
}

resource "aws_db_instance" "this" {
  identifier = "${var.project_name}-postgres"

  engine         = "postgres"
  engine_version = "16.4"
  instance_class = var.db_instance_class

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true

  multi_az               = true
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"

  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project_name}-postgres-final"

  tags = { Name = "${var.project_name}-postgres" }
}
