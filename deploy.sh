#!/bin/bash

echo "Starting deployment of ShopKart Customer Care Crew..."

# Ensure we have the .env file
if [ ! -f .env ]; then
    echo "Warning: .env file not found. Creating one from .env.example - add your API key to it!"
    cp .env.example .env
fi

# Stop any running containers
echo "Stopping existing containers..."
docker compose down

# Build and start the services in detached mode
echo "Building and starting Docker containers..."
docker compose up --build -d

echo "Deployment complete!"
echo "Frontend (Chat UI)      : http://localhost:8501"
echo "Agent API (Swagger)     : http://localhost:8000/docs"
echo "MCP Server (health)     : http://localhost:8003/health"
echo "Order Service API       : http://localhost:8001/docs"
echo "Policy Service API      : http://localhost:8002/docs"
echo "Escalation Service API  : http://localhost:8004/docs"
