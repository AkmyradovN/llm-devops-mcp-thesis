# =============================================================================
# Manual Baseline Infrastructure for MCP Server Deployment
# =============================================================================
# This configuration provisions a single EC2 instance on AWS with Docker
# pre-installed, ready to host two MCP servers (Jira on port 80, GitHub
# Issues on port 81). Part of the manual baseline for the MSc thesis:
# "LLM-Assisted DevOps for Automated Deployment and Management of MCP
#  Servers on Cloud Platforms"
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# -----------------------------------------------------------------------------
# Provider
# -----------------------------------------------------------------------------
provider "aws" {
  region = var.region
  profile = "personal"
}

# -----------------------------------------------------------------------------
# Data source: look up the latest Ubuntu 22.04 LTS AMI automatically
# This avoids hard-coding AMI IDs that differ per region and change over time.
# -----------------------------------------------------------------------------
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical (official Ubuntu publisher)

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# -----------------------------------------------------------------------------
# Security Group
# Allows inbound traffic on:
#   - Port 22  (SSH for deployment and debugging)
#   - Port 80  (MCP-Jira server)
#   - Port 81  (MCP-GitHub server)
# All outbound traffic is allowed (required for apt-get, pip, Docker pulls).
# -----------------------------------------------------------------------------
resource "aws_security_group" "mcp_servers" {
  name        = "${var.project_name}-sg"
  description = "Allow SSH, MCP-Jira (80), and MCP-GitHub (81) inbound traffic"

  # SSH access
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # MCP-Jira server
  ingress {
    description = "MCP-Jira HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # MCP-GitHub server
  ingress {
    description = "MCP-GitHub HTTP"
    from_port   = 81
    to_port     = 81
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # All outbound
  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project_name}-sg"
    Project = var.project_name
  }
}

# -----------------------------------------------------------------------------
# EC2 Instance
# Uses a user-data script to install Docker on first boot. This ensures
# the instance is ready for container deployment as soon as it's reachable.
# -----------------------------------------------------------------------------
resource "aws_instance" "mcp_host" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.mcp_servers.id]

  # User-data script: runs once on first boot
  # Installs Docker, enables it, and adds the ubuntu user to the docker group
  user_data = <<-EOF
    #!/bin/bash
    set -e

    # Update package index
    apt-get update -y

    # Install Docker from official Ubuntu repository
    apt-get install -y docker.io docker-compose

    # Start and enable Docker service
    systemctl start docker
    systemctl enable docker

    # Add ubuntu user to docker group (avoids needing sudo for docker commands)
    usermod -aG docker ubuntu

    # Log completion for debugging
    echo "Docker installation complete" > /home/ubuntu/setup_complete.txt
  EOF

  # Ensure user-data changes trigger instance replacement
  user_data_replace_on_change = true

  tags = {
    Name    = "${var.project_name}-host"
    Project = var.project_name
  }
}