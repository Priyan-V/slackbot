# Use officia Python runtime
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy required dependencies
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app
COPY . .

# Expose port (not used in Socket Mode but required)
EXPOSE 3000

# Start the Slackbot
CMD ["python", "app.py"]

