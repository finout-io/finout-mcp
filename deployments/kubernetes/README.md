# VECTIQOR Kubernetes Deployment

Deploy VECTIQOR (Ask the Smart AI of Finout) to Kubernetes for internal use.

## Quick Start

```bash
# 1. Build and push Docker image
./scripts/build-vectiqor.sh v1.0.0

# 2. Configure secrets
cp deployments/kubernetes/vectiqor-secret.yaml.example deployments/kubernetes/vectiqor-secret.yaml
# Edit vectiqor-secret.yaml with your credentials (base64 encoded)

# 3. Update configuration
nano deployments/kubernetes/vectiqor-configmap.yaml

# 4. Update ingress hostname
nano deployments/kubernetes/vectiqor-ingress.yaml

# 5. Deploy
./scripts/deploy-vectiqor-k8s.sh
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
./scripts/build-vectiqor.sh v1.0.0
```

Or manually:

```bash
# Azure Container Registry
az acr login --name your-registry
docker build -f deployments/docker/Dockerfile.vectiqor -t your-registry.azurecr.io/vectiqor:v1.0.0 .
docker push your-registry.azurecr.io/vectiqor:v1.0.0

# AWS ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin your-account.dkr.ecr.us-east-1.amazonaws.com
docker build -f deployments/docker/Dockerfile.vectiqor -t your-account.dkr.ecr.us-east-1.amazonaws.com/vectiqor:v1.0.0 .
docker push your-account.dkr.ecr.us-east-1.amazonaws.com/vectiqor:v1.0.0

# Google Container Registry
gcloud auth configure-docker
docker build -f deployments/docker/Dockerfile.vectiqor -t gcr.io/your-project/vectiqor:v1.0.0 .
docker push gcr.io/your-project/vectiqor:v1.0.0
```

### 2. Configure Secrets

**Option A: Using kubectl (Simple)**

```bash
# Create namespace
kubectl create namespace vectiqor

# Create secret
kubectl create secret generic vectiqor-secrets \
  --from-literal=finout-client-id="your-client-id" \
  --from-literal=finout-secret-key="your-secret-key" \
  --from-literal=anthropic-api-key="your-anthropic-key" \
  -n vectiqor
```

**Option B: Using YAML file**

```bash
# Copy template
cp vectiqor-secret.yaml.example vectiqor-secret.yaml

# Encode your credentials
echo -n "your-finout-client-id" | base64
echo -n "your-finout-secret-key" | base64
echo -n "your-anthropic-api-key" | base64

# Edit vectiqor-secret.yaml with encoded values
nano vectiqor-secret.yaml

# Apply
kubectl apply -f vectiqor-secret.yaml
```

**Option C: Using External Secrets (Recommended for Production)**

Azure Key Vault example:

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: vectiqor-secrets-provider
  namespace: vectiqor
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
  - secretName: vectiqor-secrets
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

Edit `vectiqor-configmap.yaml`:

```yaml
data:
  finout-internal-api-url: "http://finout-app.your-company.internal"
  finout-default-account-id: "your-default-account-id"
  log-level: "INFO"
```

### 4. Update Deployment

Edit `vectiqor-deployment.yaml`:

```yaml
spec:
  replicas: 2  # Adjust based on usage
  template:
    spec:
      containers:
      - name: vectiqor
        image: your-registry.azurecr.io/vectiqor:v1.0.0  # Update with your image
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
```

### 5. Configure Ingress

Edit `vectiqor-ingress.yaml`:

```yaml
spec:
  tls:
  - hosts:
    - vectiqor.your-company.internal  # Your hostname
    secretName: vectiqor-tls-cert     # Your TLS certificate secret
  rules:
  - host: vectiqor.your-company.internal
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: vectiqor
            port:
              number: 80
```

### 6. Deploy

```bash
# Using deployment script
./scripts/deploy-vectiqor-k8s.sh

# Or manually
kubectl apply -f deployments/kubernetes/namespace.yaml
kubectl apply -f deployments/kubernetes/vectiqor-configmap.yaml
kubectl apply -f deployments/kubernetes/vectiqor-secret.yaml
kubectl apply -f deployments/kubernetes/vectiqor-deployment.yaml
kubectl apply -f deployments/kubernetes/vectiqor-service.yaml
kubectl apply -f deployments/kubernetes/vectiqor-ingress.yaml

# Or using kustomize
kubectl apply -k deployments/kubernetes/
```

## Verification

### Check Deployment Status

```bash
# Get all resources
kubectl get all -n vectiqor -l app=vectiqor

# Check pods
kubectl get pods -n vectiqor

# Check deployment
kubectl describe deployment vectiqor -n vectiqor

# View logs
kubectl logs -n vectiqor -l app=vectiqor -f

# Check service
kubectl get svc vectiqor -n vectiqor

# Check ingress
kubectl get ingress vectiqor -n vectiqor
```

### Health Check

```bash
# Port forward for local testing
kubectl port-forward -n vectiqor svc/vectiqor 8000:80

# Test health endpoint
curl http://localhost:8000/api/health
```

### Access Application

```bash
# Get ingress URL
kubectl get ingress vectiqor -n vectiqor

# Access via browser
https://vectiqor.your-company.internal
```

## Scaling

### Manual Scaling

```bash
# Scale up
kubectl scale deployment vectiqor -n vectiqor --replicas=5

# Scale down
kubectl scale deployment vectiqor -n vectiqor --replicas=1
```

### Auto-scaling (HPA)

Create `vectiqor-hpa.yaml`:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: vectiqor
  namespace: vectiqor
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: vectiqor
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
kubectl apply -f vectiqor-hpa.yaml
```

## Updates

### Rolling Update

```bash
# Build new version
./scripts/build-vectiqor.sh v1.1.0

# Update deployment image
kubectl set image deployment/vectiqor vectiqor=your-registry.azurecr.io/vectiqor:v1.1.0 -n vectiqor

# Watch rollout
kubectl rollout status deployment/vectiqor -n vectiqor

# Rollback if needed
kubectl rollout undo deployment/vectiqor -n vectiqor
```

### Update Configuration

```bash
# Edit configmap
kubectl edit configmap vectiqor-config -n vectiqor

# Restart pods to pick up changes
kubectl rollout restart deployment/vectiqor -n vectiqor
```

## Monitoring

### Logs

```bash
# Stream logs from all pods
kubectl logs -n vectiqor -l app=vectiqor -f

# Logs from specific pod
kubectl logs -n vectiqor <pod-name> -f

# Previous logs (after crash)
kubectl logs -n vectiqor <pod-name> --previous
```

### Metrics

```bash
# Resource usage
kubectl top pods -n vectiqor -l app=vectiqor

# Detailed pod info
kubectl describe pod <pod-name> -n vectiqor
```

### Events

```bash
# Recent events
kubectl get events -n vectiqor --sort-by='.lastTimestamp'
```

## Troubleshooting

### Pod Not Starting

```bash
# Check pod status
kubectl get pods -n vectiqor

# Describe pod
kubectl describe pod <pod-name> -n vectiqor

# Check logs
kubectl logs <pod-name> -n vectiqor

# Common issues:
# - ImagePullBackOff: Check image name and registry credentials
# - CrashLoopBackOff: Check logs for application errors
# - Pending: Check resource availability and node selectors
```

### Secret Issues

```bash
# Verify secret exists
kubectl get secret vectiqor-secrets -n vectiqor

# Check secret contents (base64 encoded)
kubectl get secret vectiqor-secrets -n vectiqor -o yaml

# Recreate secret
kubectl delete secret vectiqor-secrets -n vectiqor
kubectl create secret generic vectiqor-secrets \
  --from-literal=finout-client-id="..." \
  -n vectiqor
```

### Service Not Accessible

```bash
# Check service
kubectl get svc vectiqor -n vectiqor

# Check endpoints
kubectl get endpoints vectiqor -n vectiqor

# Port forward for testing
kubectl port-forward svc/vectiqor 8000:80 -n vectiqor
curl http://localhost:8000/api/health
```

### Ingress Issues

```bash
# Check ingress
kubectl describe ingress vectiqor -n vectiqor

# Check ingress controller logs
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx -f

# Test with port-forward first
kubectl port-forward svc/vectiqor 8000:80 -n vectiqor
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
     name: vectiqor-network-policy
     namespace: vectiqor
   spec:
     podSelector:
       matchLabels:
         app: vectiqor
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
   - Limit who can deploy/update VECTIQOR
   - Use service accounts with minimal permissions

4. **Enable Pod Security Standards**
   ```yaml
   apiVersion: policy/v1beta1
   kind: PodSecurityPolicy
   metadata:
     name: vectiqor-psp
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
# Delete all VECTIQOR resources
kubectl delete -k deployments/kubernetes/

# Or manually
kubectl delete namespace vectiqor

# Delete specific resources
kubectl delete deployment vectiqor -n vectiqor
kubectl delete service vectiqor -n vectiqor
kubectl delete ingress vectiqor -n vectiqor
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Deploy VECTIQOR to K8s

on:
  push:
    branches: [main]
    paths:
      - 'tools/vectiqor/**'
      - 'deployments/kubernetes/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3

    - name: Build and push Docker image
      run: |
        docker build -f deployments/docker/Dockerfile.vectiqor -t ${{ secrets.REGISTRY }}/vectiqor:${{ github.sha }} .
        docker push ${{ secrets.REGISTRY }}/vectiqor:${{ github.sha }}

    - name: Deploy to Kubernetes
      run: |
        kubectl set image deployment/vectiqor vectiqor=${{ secrets.REGISTRY }}/vectiqor:${{ github.sha }} -n vectiqor
```

## Support

- Check logs: `kubectl logs -n vectiqor -l app=vectiqor -f`
- Check health: `kubectl get pods -n vectiqor`
- Port forward for testing: `kubectl port-forward -n vectiqor svc/vectiqor 8000:80`
- Describe resources: `kubectl describe deployment vectiqor -n vectiqor`
