# BILLY Kubernetes Deployment

Deploy BILLY (Ask the Smart AI of Finout) to Kubernetes for internal use.

## Quick Start

```bash
# 1. Build and push Docker image
./scripts/build-billy.sh v1.0.0

# 2. Configure secrets
cp deployments/kubernetes/billy-secret.yaml.example deployments/kubernetes/billy-secret.yaml
# Edit billy-secret.yaml with your credentials (base64 encoded)

# 3. Update configuration
nano deployments/kubernetes/billy-configmap.yaml

# 4. Update ingress hostname
nano deployments/kubernetes/billy-ingress.yaml

# 5. Deploy
./scripts/deploy-billy-k8s.sh
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
./scripts/build-billy.sh v1.0.0
```

Or manually:

```bash
# Azure Container Registry
az acr login --name your-registry
docker build -f deployments/docker/Dockerfile.billy -t your-registry.azurecr.io/billy:v1.0.0 .
docker push your-registry.azurecr.io/billy:v1.0.0

# AWS ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin your-account.dkr.ecr.us-east-1.amazonaws.com
docker build -f deployments/docker/Dockerfile.billy -t your-account.dkr.ecr.us-east-1.amazonaws.com/billy:v1.0.0 .
docker push your-account.dkr.ecr.us-east-1.amazonaws.com/billy:v1.0.0

# Google Container Registry
gcloud auth configure-docker
docker build -f deployments/docker/Dockerfile.billy -t gcr.io/your-project/billy:v1.0.0 .
docker push gcr.io/your-project/billy:v1.0.0
```

### 2. Configure Secrets

**Option A: Using kubectl (Simple)**

```bash
# Create namespace
kubectl create namespace billy

# Create secret
kubectl create secret generic billy-secrets \
  --from-literal=finout-client-id="your-client-id" \
  --from-literal=finout-secret-key="your-secret-key" \
  --from-literal=anthropic-api-key="your-anthropic-key" \
  -n billy
```

**Option B: Using YAML file**

```bash
# Copy template
cp billy-secret.yaml.example billy-secret.yaml

# Encode your credentials
echo -n "your-finout-client-id" | base64
echo -n "your-finout-secret-key" | base64
echo -n "your-anthropic-api-key" | base64

# Edit billy-secret.yaml with encoded values
nano billy-secret.yaml

# Apply
kubectl apply -f billy-secret.yaml
```

**Option C: Using External Secrets (Recommended for Production)**

Azure Key Vault example:

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: billy-secrets-provider
  namespace: billy
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
  - secretName: billy-secrets
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

Edit `billy-configmap.yaml`:

```yaml
data:
  finout-internal-api-url: "http://finout-app.your-company.internal"
  finout-default-account-id: "your-default-account-id"
  log-level: "INFO"
```

### 4. Update Deployment

Edit `billy-deployment.yaml`:

```yaml
spec:
  replicas: 2  # Adjust based on usage
  template:
    spec:
      containers:
      - name: billy
        image: your-registry.azurecr.io/billy:v1.0.0  # Update with your image
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
```

### 5. Configure Ingress

Edit `billy-ingress.yaml`:

```yaml
spec:
  tls:
  - hosts:
    - billy.your-company.internal  # Your hostname
    secretName: billy-tls-cert     # Your TLS certificate secret
  rules:
  - host: billy.your-company.internal
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: billy
            port:
              number: 80
```

### 6. Deploy

```bash
# Using deployment script
./scripts/deploy-billy-k8s.sh

# Or manually
kubectl apply -f deployments/kubernetes/namespace.yaml
kubectl apply -f deployments/kubernetes/billy-configmap.yaml
kubectl apply -f deployments/kubernetes/billy-secret.yaml
kubectl apply -f deployments/kubernetes/billy-deployment.yaml
kubectl apply -f deployments/kubernetes/billy-service.yaml
kubectl apply -f deployments/kubernetes/billy-ingress.yaml

# Or using kustomize
kubectl apply -k deployments/kubernetes/
```

## Verification

### Check Deployment Status

```bash
# Get all resources
kubectl get all -n billy -l app=billy

# Check pods
kubectl get pods -n billy

# Check deployment
kubectl describe deployment billy -n billy

# View logs
kubectl logs -n billy -l app=billy -f

# Check service
kubectl get svc billy -n billy

# Check ingress
kubectl get ingress billy -n billy
```

### Health Check

```bash
# Port forward for local testing
kubectl port-forward -n billy svc/billy 8000:80

# Test health endpoint
curl http://localhost:8000/api/health
```

### Access Application

```bash
# Get ingress URL
kubectl get ingress billy -n billy

# Access via browser
https://billy.your-company.internal
```

## Scaling

### Manual Scaling

```bash
# Scale up
kubectl scale deployment billy -n billy --replicas=5

# Scale down
kubectl scale deployment billy -n billy --replicas=1
```

### Auto-scaling (HPA)

Create `billy-hpa.yaml`:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: billy
  namespace: billy
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: billy
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
kubectl apply -f billy-hpa.yaml
```

## Updates

### Rolling Update

```bash
# Build new version
./scripts/build-billy.sh v1.1.0

# Update deployment image
kubectl set image deployment/billy billy=your-registry.azurecr.io/billy:v1.1.0 -n billy

# Watch rollout
kubectl rollout status deployment/billy -n billy

# Rollback if needed
kubectl rollout undo deployment/billy -n billy
```

### Update Configuration

```bash
# Edit configmap
kubectl edit configmap billy-config -n billy

# Restart pods to pick up changes
kubectl rollout restart deployment/billy -n billy
```

## Monitoring

### Logs

```bash
# Stream logs from all pods
kubectl logs -n billy -l app=billy -f

# Logs from specific pod
kubectl logs -n billy <pod-name> -f

# Previous logs (after crash)
kubectl logs -n billy <pod-name> --previous
```

### Metrics

```bash
# Resource usage
kubectl top pods -n billy -l app=billy

# Detailed pod info
kubectl describe pod <pod-name> -n billy
```

### Events

```bash
# Recent events
kubectl get events -n billy --sort-by='.lastTimestamp'
```

## Troubleshooting

### Pod Not Starting

```bash
# Check pod status
kubectl get pods -n billy

# Describe pod
kubectl describe pod <pod-name> -n billy

# Check logs
kubectl logs <pod-name> -n billy

# Common issues:
# - ImagePullBackOff: Check image name and registry credentials
# - CrashLoopBackOff: Check logs for application errors
# - Pending: Check resource availability and node selectors
```

### Secret Issues

```bash
# Verify secret exists
kubectl get secret billy-secrets -n billy

# Check secret contents (base64 encoded)
kubectl get secret billy-secrets -n billy -o yaml

# Recreate secret
kubectl delete secret billy-secrets -n billy
kubectl create secret generic billy-secrets \
  --from-literal=finout-client-id="..." \
  -n billy
```

### Service Not Accessible

```bash
# Check service
kubectl get svc billy -n billy

# Check endpoints
kubectl get endpoints billy -n billy

# Port forward for testing
kubectl port-forward svc/billy 8000:80 -n billy
curl http://localhost:8000/api/health
```

### Ingress Issues

```bash
# Check ingress
kubectl describe ingress billy -n billy

# Check ingress controller logs
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx -f

# Test with port-forward first
kubectl port-forward svc/billy 8000:80 -n billy
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
     name: billy-network-policy
     namespace: billy
   spec:
     podSelector:
       matchLabels:
         app: billy
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
   - Limit who can deploy/update BILLY
   - Use service accounts with minimal permissions

4. **Enable Pod Security Standards**
   ```yaml
   apiVersion: policy/v1beta1
   kind: PodSecurityPolicy
   metadata:
     name: billy-psp
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
# Delete all BILLY resources
kubectl delete -k deployments/kubernetes/

# Or manually
kubectl delete namespace billy

# Delete specific resources
kubectl delete deployment billy -n billy
kubectl delete service billy -n billy
kubectl delete ingress billy -n billy
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Deploy BILLY to K8s

on:
  push:
    branches: [main]
    paths:
      - 'tools/billy/**'
      - 'deployments/kubernetes/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3

    - name: Build and push Docker image
      run: |
        docker build -f deployments/docker/Dockerfile.billy -t ${{ secrets.REGISTRY }}/billy:${{ github.sha }} .
        docker push ${{ secrets.REGISTRY }}/billy:${{ github.sha }}

    - name: Deploy to Kubernetes
      run: |
        kubectl set image deployment/billy billy=${{ secrets.REGISTRY }}/billy:${{ github.sha }} -n billy
```

## Support

- Check logs: `kubectl logs -n billy -l app=billy -f`
- Check health: `kubectl get pods -n billy`
- Port forward for testing: `kubectl port-forward -n billy svc/billy 8000:80`
- Describe resources: `kubectl describe deployment billy -n billy`
