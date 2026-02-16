# ASAF Kubernetes Deployment

Deploy ASAF (Ask the Smart AI of Finout) to Kubernetes for internal use.

## Quick Start

```bash
# 1. Build and push Docker image
./scripts/build-asaf.sh v1.0.0

# 2. Configure secrets
cp deployments/kubernetes/asaf-secret.yaml.example deployments/kubernetes/asaf-secret.yaml
# Edit asaf-secret.yaml with your credentials (base64 encoded)

# 3. Update configuration
nano deployments/kubernetes/asaf-configmap.yaml

# 4. Update ingress hostname
nano deployments/kubernetes/asaf-ingress.yaml

# 5. Deploy
./scripts/deploy-asaf-k8s.sh
```

## Prerequisites

- Kubernetes cluster (1.19+)
- `kubectl` configured and connected
- Docker registry (ACR, ECR, GCR, or Docker Hub)
- Ingress controller (NGINX, Azure App Gateway, or AWS ALB)
- TLS certificate for HTTPS (optional but recommended)

## Detailed Setup

### 1. Build Docker Image

```bash
# Set your registry
export DOCKER_REGISTRY=your-registry.azurecr.io

# Build and push
./scripts/build-asaf.sh v1.0.0
```

Or manually:

```bash
# Azure Container Registry
az acr login --name your-registry
docker build -f deployments/docker/Dockerfile.asaf -t your-registry.azurecr.io/asaf:v1.0.0 .
docker push your-registry.azurecr.io/asaf:v1.0.0

# AWS ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin your-account.dkr.ecr.us-east-1.amazonaws.com
docker build -f deployments/docker/Dockerfile.asaf -t your-account.dkr.ecr.us-east-1.amazonaws.com/asaf:v1.0.0 .
docker push your-account.dkr.ecr.us-east-1.amazonaws.com/asaf:v1.0.0

# Google Container Registry
gcloud auth configure-docker
docker build -f deployments/docker/Dockerfile.asaf -t gcr.io/your-project/asaf:v1.0.0 .
docker push gcr.io/your-project/asaf:v1.0.0
```

### 2. Configure Secrets

**Option A: Using kubectl (Simple)**

```bash
# Create namespace
kubectl create namespace asaf

# Create secret
kubectl create secret generic asaf-secrets \
  --from-literal=finout-client-id="your-client-id" \
  --from-literal=finout-secret-key="your-secret-key" \
  --from-literal=anthropic-api-key="your-anthropic-key" \
  -n asaf
```

**Option B: Using YAML file**

```bash
# Copy template
cp asaf-secret.yaml.example asaf-secret.yaml

# Encode your credentials
echo -n "your-finout-client-id" | base64
echo -n "your-finout-secret-key" | base64
echo -n "your-anthropic-api-key" | base64

# Edit asaf-secret.yaml with encoded values
nano asaf-secret.yaml

# Apply
kubectl apply -f asaf-secret.yaml
```

**Option C: Using External Secrets (Recommended for Production)**

Azure Key Vault example:

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: asaf-secrets-provider
  namespace: asaf
spec:
  provider: azure
  parameters:
    keyvaultName: "your-keyvault"
    objects: |
      array:
        - |
          objectName: finout-client-id
          objectType: secret
        - |
          objectName: finout-secret-key
          objectType: secret
        - |
          objectName: anthropic-api-key
          objectType: secret
  secretObjects:
  - secretName: asaf-secrets
    type: Opaque
    data:
    - objectName: finout-client-id
      key: finout-client-id
    - objectName: finout-secret-key
      key: finout-secret-key
    - objectName: anthropic-api-key
      key: anthropic-api-key
```

### 3. Update Configuration

Edit `asaf-configmap.yaml`:

```yaml
data:
  finout-internal-api-url: "http://finout-app.your-company.internal"
  finout-default-account-id: "your-default-account-id"
  log-level: "INFO"
```

### 4. Update Deployment

Edit `asaf-deployment.yaml`:

```yaml
spec:
  replicas: 2  # Adjust based on usage
  template:
    spec:
      containers:
      - name: asaf
        image: your-registry.azurecr.io/asaf:v1.0.0  # Update with your image
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
```

### 5. Configure Ingress

Edit `asaf-ingress.yaml`:

```yaml
spec:
  tls:
  - hosts:
    - asaf.your-company.internal  # Your hostname
    secretName: asaf-tls-cert     # Your TLS certificate secret
  rules:
  - host: asaf.your-company.internal
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: asaf
            port:
              number: 80
```

### 6. Deploy

```bash
# Using deployment script
./scripts/deploy-asaf-k8s.sh

# Or manually
kubectl apply -f deployments/kubernetes/namespace.yaml
kubectl apply -f deployments/kubernetes/asaf-configmap.yaml
kubectl apply -f deployments/kubernetes/asaf-secret.yaml
kubectl apply -f deployments/kubernetes/asaf-deployment.yaml
kubectl apply -f deployments/kubernetes/asaf-service.yaml
kubectl apply -f deployments/kubernetes/asaf-ingress.yaml

# Or using kustomize
kubectl apply -k deployments/kubernetes/
```

## Verification

### Check Deployment Status

```bash
# Get all resources
kubectl get all -n asaf -l app=asaf

# Check pods
kubectl get pods -n asaf

# Check deployment
kubectl describe deployment asaf -n asaf

# View logs
kubectl logs -n asaf -l app=asaf -f

# Check service
kubectl get svc asaf -n asaf

# Check ingress
kubectl get ingress asaf -n asaf
```

### Health Check

```bash
# Port forward for local testing
kubectl port-forward -n asaf svc/asaf 8000:80

# Test health endpoint
curl http://localhost:8000/api/health
```

### Access Application

```bash
# Get ingress URL
kubectl get ingress asaf -n asaf

# Access via browser
https://asaf.your-company.internal
```

## Scaling

### Manual Scaling

```bash
# Scale up
kubectl scale deployment asaf -n asaf --replicas=5

# Scale down
kubectl scale deployment asaf -n asaf --replicas=1
```

### Auto-scaling (HPA)

Create `asaf-hpa.yaml`:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: asaf
  namespace: asaf
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: asaf
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

Apply:
```bash
kubectl apply -f asaf-hpa.yaml
```

## Updates

### Rolling Update

```bash
# Build new version
./scripts/build-asaf.sh v1.1.0

# Update deployment image
kubectl set image deployment/asaf asaf=your-registry.azurecr.io/asaf:v1.1.0 -n asaf

# Watch rollout
kubectl rollout status deployment/asaf -n asaf

# Rollback if needed
kubectl rollout undo deployment/asaf -n asaf
```

### Update Configuration

```bash
# Edit configmap
kubectl edit configmap asaf-config -n asaf

# Restart pods to pick up changes
kubectl rollout restart deployment/asaf -n asaf
```

## Monitoring

### Logs

```bash
# Stream logs from all pods
kubectl logs -n asaf -l app=asaf -f

# Logs from specific pod
kubectl logs -n asaf <pod-name> -f

# Previous logs (after crash)
kubectl logs -n asaf <pod-name> --previous
```

### Metrics

```bash
# Resource usage
kubectl top pods -n asaf -l app=asaf

# Detailed pod info
kubectl describe pod <pod-name> -n asaf
```

### Events

```bash
# Recent events
kubectl get events -n asaf --sort-by='.lastTimestamp'
```

## Troubleshooting

### Pod Not Starting

```bash
# Check pod status
kubectl get pods -n asaf

# Describe pod
kubectl describe pod <pod-name> -n asaf

# Check logs
kubectl logs <pod-name> -n asaf

# Common issues:
# - ImagePullBackOff: Check image name and registry credentials
# - CrashLoopBackOff: Check logs for application errors
# - Pending: Check resource availability and node selectors
```

### Secret Issues

```bash
# Verify secret exists
kubectl get secret asaf-secrets -n asaf

# Check secret contents (base64 encoded)
kubectl get secret asaf-secrets -n asaf -o yaml

# Recreate secret
kubectl delete secret asaf-secrets -n asaf
kubectl create secret generic asaf-secrets \
  --from-literal=finout-client-id="..." \
  -n asaf
```

### Service Not Accessible

```bash
# Check service
kubectl get svc asaf -n asaf

# Check endpoints
kubectl get endpoints asaf -n asaf

# Port forward for testing
kubectl port-forward svc/asaf 8000:80 -n asaf
curl http://localhost:8000/api/health
```

### Ingress Issues

```bash
# Check ingress
kubectl describe ingress asaf -n asaf

# Check ingress controller logs
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx -f

# Test with port-forward first
kubectl port-forward svc/asaf 8000:80 -n asaf
```

## Security Best Practices

1. **Use Secrets Management**
   - Azure Key Vault, AWS Secrets Manager, or HashiCorp Vault
   - Never commit secrets to git

2. **Enable Network Policies**
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: asaf-network-policy
     namespace: asaf
   spec:
     podSelector:
       matchLabels:
         app: asaf
     policyTypes:
     - Ingress
     - Egress
     ingress:
     - from:
       - namespaceSelector:
           matchLabels:
             name: ingress-nginx
       ports:
       - protocol: TCP
         port: 8000
     egress:
     - to:
       - namespaceSelector: {}
       ports:
       - protocol: TCP
         port: 443
   ```

3. **Use RBAC**
   - Limit who can deploy/update ASAF
   - Use service accounts with minimal permissions

4. **Enable Pod Security Standards**
   ```yaml
   apiVersion: policy/v1beta1
   kind: PodSecurityPolicy
   metadata:
     name: asaf-psp
   spec:
     privileged: false
     allowPrivilegeEscalation: false
     runAsUser:
       rule: MustRunAsNonRoot
     seLinux:
       rule: RunAsAny
     fsGroup:
       rule: RunAsAny
     volumes:
     - configMap
     - secret
     - emptyDir
   ```

5. **Use TLS**
   - Always use HTTPS in production
   - Obtain certificates from Let's Encrypt or your CA

## Cleanup

```bash
# Delete all ASAF resources
kubectl delete -k deployments/kubernetes/

# Or manually
kubectl delete namespace asaf

# Delete specific resources
kubectl delete deployment asaf -n asaf
kubectl delete service asaf -n asaf
kubectl delete ingress asaf -n asaf
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Deploy ASAF to K8s

on:
  push:
    branches: [main]
    paths:
      - 'tools/asaf/**'
      - 'deployments/kubernetes/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3

    - name: Build and push Docker image
      run: |
        docker build -f deployments/docker/Dockerfile.asaf -t ${{ secrets.REGISTRY }}/asaf:${{ github.sha }} .
        docker push ${{ secrets.REGISTRY }}/asaf:${{ github.sha }}

    - name: Deploy to Kubernetes
      run: |
        kubectl set image deployment/asaf asaf=${{ secrets.REGISTRY }}/asaf:${{ github.sha }} -n asaf
```

## Support

- Check logs: `kubectl logs -n asaf -l app=asaf -f`
- Check health: `kubectl get pods -n asaf`
- Port forward for testing: `kubectl port-forward -n asaf svc/asaf 8000:80`
- Describe resources: `kubectl describe deployment asaf -n asaf`
