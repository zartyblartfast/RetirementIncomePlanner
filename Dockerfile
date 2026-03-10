# Retirement Income Planner — Docker Image
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .
COPY retirement_engine.py .
COPY optimiser.py .
COPY market_data.py .
COPY retirement_planner.py .

# Copy configuration defaults and asset model
COPY config_default.json .
COPY asset_model.json .

# Copy web assets
COPY templates/ templates/
COPY static/ static/

# Copy documentation (served by the app)
COPY HOW_IT_WORKS.html .

# Create directories for persistent data (mount as volumes)
RUN mkdir -p /app/scenarios /app/output

# Default port — Gunicorn binds here inside the container
EXPOSE 8000

# Run with Gunicorn (workers configurable via env)
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "120", \
     "app:app"]
