# Use the Python runtime
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy dependencies
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app
COPY . .

# Expose port 
EXPOSE 3000

# Start the Slackbot
CMD ["python", "app.py"]
