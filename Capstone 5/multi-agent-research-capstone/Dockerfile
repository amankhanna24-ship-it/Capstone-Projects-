# Dockerfile - instructions for building a "container" that runs our MCP server.
#
# A container is like a sealed lunchbox: it holds the code AND everything the
# code needs (Python, libraries). It runs the same on your laptop, a classmate's
# laptop or a cloud server - no more "but it works on my machine".
#
# Build and run:   docker compose up --build

# 1. Start from an official, small Python image
FROM python:3.11-slim

# 2. Sensible Python settings for containers
#    - don't write .pyc files, and print logs straight away
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

# 3. Work inside /app in the container
WORKDIR /app

# 4. Install ONLY the server's libraries (not CrewAI/ADK - the server doesn't need them).
#    We copy the requirements file first so Docker can cache this slow step.
COPY requirements-mcp.txt .
RUN pip install --no-cache-dir -r requirements-mcp.txt

# 5. Copy our server code into the container
COPY mcp_server/ ./mcp_server/

# 6. Don't run as the all-powerful "root" user - a basic security habit
RUN useradd --create-home appuser
USER appuser

# 7. Tell Docker which port the server listens on
EXPOSE 8000

# 8. Docker checks every 30 seconds that the server is still answering
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 9. The command that runs when the container starts
CMD ["python", "-m", "mcp_server.server"]
