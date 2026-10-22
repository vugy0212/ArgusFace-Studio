FROM python:3.11-slim

WORKDIR /app

# Install minimal system requirements
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot application
COPY bot.py .

CMD ["python", "bot.py"]
