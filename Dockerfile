# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Copy & install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your bot code
COPY . .

# Launch
CMD ["python", "bot.py"]
