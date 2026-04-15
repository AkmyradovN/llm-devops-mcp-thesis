variable "region" {
  description = "AWS region for all resources"
  type        = string
  default     = "eu-central-1"
}

variable "instance_type" {
  description = "EC2 instance type (t3.micro is free-tier eligible in eu-central-1)"
  type        = string
  default     = "t3.micro"
}

variable "key_name" {
  description = "Name of an existing AWS key pair for SSH access"
  type        = string
}

variable "project_name" {
  description = "Prefix used for naming all resources (tags, security group, etc.)"
  type        = string
  default     = "mcp-thesis"
}