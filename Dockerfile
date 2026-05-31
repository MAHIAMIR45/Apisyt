# Base image Python ki use karein
FROM python:3.10-slim

# System packages update karein aur FFmpeg install karein
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Working directory set karein
WORKDIR /app

# Requirements copy aur install karein
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baqi ka poora code copy karein
COPY . .

# Port expose karein
EXPOSE 10000

# App ko gunicorn ke sath run karein (Render ke liye best hai)
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "app:app", "--timeout", "120"]
