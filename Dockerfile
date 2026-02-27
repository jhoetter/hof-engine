# Multi-stage Dockerfile for hof-engine applications
# Stage 1: Python dependencies
FROM python:3.11-slim AS python-deps

WORKDIR /app

# Install system dependencies required by psycopg2 and other packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e ".[dev]"

# Stage 2: Node.js for building the admin UI and user UI
FROM node:20-slim AS node-builder

WORKDIR /app/hof/ui/admin
COPY hof/ui/admin/package*.json ./
RUN npm ci --silent

COPY hof/ui/admin/ ./
RUN npm run build

# Stage 3: Final runtime image
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from deps stage
COPY --from=python-deps /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=python-deps /usr/local/bin /usr/local/bin

# Copy application source
COPY hof/ ./hof/
COPY pyproject.toml ./

# Copy built admin UI
COPY --from=node-builder /app/hof/ui/admin/dist ./hof/ui/admin/dist

# Create a non-root user
RUN useradd --create-home --shell /bin/bash hof
USER hof

EXPOSE 8000

CMD ["uvicorn", "hof.api.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
