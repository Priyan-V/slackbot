# Use official Python runtime
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy dependencies
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Expose dummy port (required by Render for web service)
EXPOSE 3000

# Set environment variable for Render (optional, fallback to 3000)
ENV PORT=3000

# Start the Slackbot
CMD ["python", "app.py"]
