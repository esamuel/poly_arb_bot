FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for Docker caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project
COPY . /app/poly_arb_bot/

# Set Python path so imports work
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Expose dashboard port
EXPOSE 8080

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Run with gunicorn for production stability
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "120", "poly_arb_bot.dashboard:app"]
