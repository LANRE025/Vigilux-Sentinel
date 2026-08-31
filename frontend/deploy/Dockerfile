# Vigilux Sentinel Frontend - Cloud Run image
# Build context: repo root (e.g.  gcloud builds submit --config frontend/deploy/Dockerfile .)
#
# Multi-stage build: Node builds the Vite app, nginx serves the static dist.
# VITE_API_URL is injected at build time via --build-arg so the frontend can
# target any deployed backend without rebuilding the image.

# ---------------------------------------------------------------------------
# Stage 1: Build
# ---------------------------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

# Install deps first for better layer caching.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy source and build with the backend URL baked in.
COPY frontend/ ./

ARG VITE_API_URL
ARG VITE_DEMO=false
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Serve (nginx)
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine

# Remove default nginx config.
RUN rm /etc/nginx/conf.d/default.conf

# Copy our SPA-friendly nginx config.
COPY frontend/deploy/nginx.conf /etc/nginx/conf.d/default.conf

# Copy the built dist from the build stage.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

# nginx foreground mode.
CMD ["nginx", "-g", "daemon off;"]
