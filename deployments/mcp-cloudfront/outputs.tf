output "cloudfront_domain_name" {
  description = "CloudFront distribution domain (use for DNS validation or debugging)"
  value       = aws_cloudfront_distribution.mcp.domain_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID (for cache invalidations)"
  value       = aws_cloudfront_distribution.mcp.id
}

output "alb_security_group_id" {
  description = "Security group ID to put in the K8s ingress annotation (alb.ingress.kubernetes.io/security-groups)"
  value       = aws_security_group.alb.id
}

