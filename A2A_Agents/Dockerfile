
# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
# We use the shared requirements from the parent directory context
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
# We will build from the A2A_Agents root context, so we copy remote_agent folder
COPY remote_agent/ ./remote_agent/
# Also copy .env if we were using it for build (but better to use secrets at runtime)
# For this POC, we'll assume env vars are passed at runtime, but code expects .env file adjacent or similar.
# The code loads from .env in the same dir as agent.py.
# We'll copy the root .env to remote_agent/.env for simplicity if needed, OR just rely on env vars.
# adk/dotenv usually overrides with system env vars if present.

# Make port 8080 available to the world outside this container
EXPOSE 8080

# Define environment variable
# ENV NAME World

# Run uvicorn when the container launches
# Host 0.0.0.0 is critical for Cloud Run
CMD ["python", "-m", "uvicorn", "remote_agent.agent:a2a_app", "--host", "0.0.0.0", "--port", "8080"]
