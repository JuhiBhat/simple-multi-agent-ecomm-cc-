Write-Host "Starting deployment of ShopKart Customer Care Crew..."

# Ensure we have the .env file
if (-Not (Test-Path ".env")) {
    Write-Host "Warning: .env file not found. Creating one from .env.example - add your API key to it!"
    Copy-Item ".env.example" ".env"
}

# Stop any running containers
Write-Host "Stopping existing containers..."
docker compose down

# Build and start the services in detached mode
Write-Host "Building and starting Docker containers..."
docker compose up --build -d

Write-Host "Deployment complete!"
Write-Host "Frontend (Chat UI)      : http://localhost:8501"
Write-Host "Agent API (Swagger)     : http://localhost:8000/docs"
Write-Host "MCP Server (health)     : http://localhost:8003/health"
Write-Host "Order Service API       : http://localhost:8001/docs"
Write-Host "Policy Service API      : http://localhost:8002/docs"
Write-Host "Escalation Service API  : http://localhost:8004/docs"
