terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.83" # VPC Origins support requires >= 5.83
    }
  }

  backend "s3" {
    bucket = "finout-terraform-state"
    key    = "mcp-cloudfront/terraform.tfstate"
    region = "us-east-1"
  }
}

# Primary provider — cluster region (ALB, SG, VPC origin)
provider "aws" {
  region = var.aws_region
}

# ── ALB security group ─────────────────────────────────────────────────────────
# Allow HTTPS inbound from CloudFront VPC origin IPs only.
# The managed prefix list covers all CloudFront origin-facing IPs globally.

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "alb" {
  name        = "finout-mcp-alb"
  description = "Allow HTTPS from CloudFront VPC origin only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "HTTPS from CloudFront VPC origin"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "finout-mcp-alb"
    cluster = var.cluster_name
  }
}

# Look up the ALB so we can create an alias record pointing to its DNS name.
data "aws_lb" "mcp" {
  arn = var.alb_arn
}

# Allow ALB → pods on port 8080 (target-type: ip routes directly to pod IPs).
resource "aws_security_group_rule" "alb_to_pods" {
  type                     = "ingress"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  security_group_id        = var.node_security_group_id
  source_security_group_id = aws_security_group.alb.id
  description              = "ALB health checks and traffic to finout-mcp pods"
}

# ── CloudFront VPC origin ──────────────────────────────────────────────────────
# Allows CloudFront to reach the internal ALB without making it internet-facing.

resource "aws_cloudfront_vpc_origin" "mcp" {
  vpc_origin_endpoint_config {
    name                   = "finout-mcp-alb"
    arn                    = var.alb_arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "https-only"

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }

  tags = {
    Name    = "finout-mcp"
    cluster = var.cluster_name
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ── CloudFront distribution ────────────────────────────────────────────────────

resource "aws_cloudfront_distribution" "mcp" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "Finout MCP hosted public — mcp.finout.io"
  aliases         = ["mcp.finout.io"]

  origin {
    origin_id   = "finout-mcp-alb"
    domain_name = var.alb_dns_name

    vpc_origin_config {
      vpc_origin_id            = aws_cloudfront_vpc_origin.mcp.id
      origin_keepalive_timeout = 60
      origin_read_timeout      = 60
    }

    custom_header {
      name  = "X-Forwarded-Proto"
      value = "https"
    }
  }

  # No caching — this is a streaming API with per-request auth.
  default_cache_behavior {
    target_origin_id       = "finout-mcp-alb"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # Managed cache policy: CachingDisabled
    cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"

    # Managed origin request policy: AllViewerExceptHostHeader
    # Forwards all headers/cookies/query strings to origin, excluding Host
    # (CloudFront replaces Host with the origin domain).
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.cloudfront_cert_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = {
    Name = "finout-mcp"
  }

  depends_on = [aws_cloudfront_vpc_origin.mcp]
}

# ── Route53 private record ────────────────────────────────────────────────────
# mcp.internal.finout.io → ALB (used by CloudFront VPC origin for DNS resolution)

resource "aws_route53_record" "mcp_internal" {
  zone_id = var.route53_private_zone_id
  name    = "mcp.internal.finout.io"
  type    = "A"

  alias {
    name                   = data.aws_lb.mcp.dns_name
    zone_id                = data.aws_lb.mcp.zone_id
    evaluate_target_health = true
  }
}

# ── Route53 public record ──────────────────────────────────────────────────────

resource "aws_route53_record" "mcp" {
  zone_id = var.route53_public_zone_id
  name    = "mcp.finout.io"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.mcp.domain_name
    zone_id                = aws_cloudfront_distribution.mcp.hosted_zone_id
    evaluate_target_health = false
  }
}
