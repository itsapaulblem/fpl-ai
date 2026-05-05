# syntax=docker/dockerfile:1.6

# ---------- builder: install deps + build the Vite bundle --------------
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install

# Build-time API base URL — overridden via `--build-arg VITE_API_BASE=...`
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=$VITE_API_BASE

COPY . .
RUN npm run build

# ---------- runtime: nginx serving static + reverse-proxying /api ------
FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q -O - http://127.0.0.1/ >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
