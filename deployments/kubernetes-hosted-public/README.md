# Hosted Public MCP on Kubernetes

Deploys the standalone hosted public MCP service (separate from VECTIQOR).

## Apply

```bash
kubectl apply -k deployments/kubernetes-hosted-public
```

## Verify

```bash
kubectl -n mcp-public get deploy,svc,ingress,pods
kubectl -n mcp-public logs deploy/finout-mcp --tail=200
```

## Health check

```bash
kubectl -n mcp-public port-forward svc/finout-mcp-hosted-public 8080:80
curl -sS http://localhost:8080/health
```

## Runtime auth model

The service does **not** store static Finout credentials in k8s.
Clients must send credentials on each MCP request using headers:

- `x-finout-client-id`
- `x-finout-secret-key`
- Optional: `x-finout-api-url` (defaults to `https://app.finout.io`)
