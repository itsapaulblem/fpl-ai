# Deployment

Phase 12 ships fpl-ai as a two-container stack:

- **backend** — FastAPI + LightGBM, served by uvicorn on port `8000`.
- **frontend** — Vite-built React SPA, served by nginx on port `80` and reverse-proxying `/api/*` to the backend container.

## 1. Local container test

```powershell
docker compose up --build
# open http://localhost:8080
```

The browser always talks to nginx, which forwards `/api/...` calls to the backend over the internal Docker network. CORS is wide-open in the backend image (`FPL_AI_CORS_ORIGINS=*`).

To stop:
```powershell
docker compose down
```

## 2. Image-only build (e.g. for pushing to a registry)

```powershell
# backend
docker build -t fpl-ai-backend:latest -f Dockerfile .

# frontend (point VITE_API_BASE at the public URL of your backend)
docker build `
    --build-arg VITE_API_BASE=https://api.your-domain.com `
    -t fpl-ai-frontend:latest `
    -f frontend/Dockerfile ./frontend
```

## 3. AWS deployment options

### Option A — single EC2 / Lightsail box (cheapest, fastest)

1. Launch an Ubuntu 22.04 instance (`t3.small` is enough for a personal project).
2. Install docker + compose, copy the repo, then:
   ```bash
   docker compose up -d --build
   ```
3. Open ports `80` (and `443` if you terminate TLS with caddy/traefik).

### Option B — ECS Fargate (managed, scales to zero is not available, ~$15/mo idle)

1. Push images to ECR:
   ```powershell
   aws ecr create-repository --repository-name fpl-ai-backend
   aws ecr create-repository --repository-name fpl-ai-frontend
   # docker tag + docker push (see ECR push commands in the AWS console)
   ```
2. Create an ECS cluster, define one task with both containers (backend + frontend), or two services behind an ALB.
3. Point Route 53 at the ALB.

### Option C — split: S3 + CloudFront for the frontend, App Runner for the backend

1. `cd frontend && VITE_API_BASE=https://<apprunner-url> npm run build`
2. `aws s3 sync dist/ s3://your-bucket --delete`
3. Front the bucket with CloudFront (and a custom domain).
4. Deploy the backend image to AWS App Runner — it scales to zero between requests and is the cheapest hosted option for low-traffic APIs.

## Environment variables

| Var | Where | Default | Purpose |
|-----|-------|---------|---------|
| `FPL_AI_CORS_ORIGINS` | backend | `""` | Comma-separated extra origins. `"*"` allows any origin. |
| `VITE_API_BASE` | frontend (build-time) | `/api` | Base URL the SPA hits. Use `/api` when sharing the nginx origin, or a fully-qualified URL for split deployments. |
