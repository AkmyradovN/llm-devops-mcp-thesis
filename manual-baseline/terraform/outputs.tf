# Outputs needed by the CI/CD pipeline and verification scripts
# After terraform apply, these values are printed to the console and can be
# queried with: terraform output public_ip

output "public_ip" {
  description = "Public IPv4 address of the MCP host (used for health checks)"
  value       = aws_instance.mcp_host.public_ip
}

output "public_dns" {
  description = "Public DNS hostname of the MCP host"
  value       = aws_instance.mcp_host.public_dns
}

output "instance_id" {
  description = "EC2 instance ID (useful for AWS Console debugging)"
  value       = aws_instance.mcp_host.id
}

output "ami_id" {
  description = "AMI ID that was selected (for reproducibility logging)"
  value       = data.aws_ami.ubuntu.id
}

output "security_group_id" {
  description = "Security group ID attached to the instance"
  value       = aws_security_group.mcp_servers.id
}