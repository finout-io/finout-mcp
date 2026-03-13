variable "aws_region" {
  description = "AWS region where the prod-data-engine cluster and ALB live"
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "prod-data-engine"
}

variable "node_security_group_id" {
  description = "EKS cluster/node security group ID. Needs inbound TCP 8080 from the ALB SG so the ALB can reach pod IPs directly (target-type: ip)."
  type        = string
  default     = "sg-053342e0afee83cc5"
}

variable "vpc_id" {
  description = "VPC ID of the prod-data-engine cluster (for the ALB security group)"
  type        = string
  default     = "vpc-07f9628106e924b83"
}

variable "alb_arn" {
  description = <<-EOT
    ARN of the internal ALB created by the Kubernetes ingress controller.
    Apply the K8s manifests first, then get this with:
      kubectl get ingress finout-mcp-hosted-public -n mcp-public \
        -o jsonpath='{.metadata.annotations.kubernetes\.io/ingress\.class}'
    Or look it up in the EC2 console under Load Balancers (tag: kubernetes.io/cluster/prod-data-engine).
  EOT
  type        = string
  default     = "arn:aws:elasticloadbalancing:us-east-1:277411487094:loadbalancer/app/k8s-mcppubli-finoutmc-6cf9567121/f056d0bfc05348f2"
}

variable "alb_dns_name" {
  description = "Internal DNS name of the ALB (used as CloudFront origin domain)"
  type        = string
  default     = "mcp.internal.finout.io"
}

variable "alb_cert_arn" {
  description = "ACM certificate ARN for the ALB HTTPS listener (must be in var.aws_region). Used in the K8s ingress annotation."
  type        = string
  default     = "arn:aws:acm:us-east-1:277411487094:certificate/2bbd2a25-b995-4420-ab94-8ed88f94d57f"
}

variable "cloudfront_cert_arn" {
  description = "Existing ACM certificate ARN for mcp.finout.io in us-east-1 (required by CloudFront). Must cover mcp.finout.io."
  type        = string
  default     = "arn:aws:acm:us-east-1:277411487094:certificate/6d779188-c7c1-47d3-a805-a92a684749fc"
}

variable "route53_public_zone_id" {
  description = "Route53 public hosted zone ID for finout.io (for mcp.finout.io record and cert validation)"
  type        = string
  default     = "Z06070293A8SM5VFNYY70"
}

variable "route53_private_zone_id" {
  description = "Route53 private hosted zone ID for internal.finout.io (for mcp.internal.finout.io)"
  type        = string
  default     = "Z067649217K758I13UCY2"
}
