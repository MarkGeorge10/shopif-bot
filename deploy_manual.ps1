# Deploy Script: Local Build -> Docker Hub -> Google Cloud Run
# Purpose: Automates the manual deployment steps for Shopify AI Concierge

# 1. Build locally
docker build -t shopify-ai-concierge-backend:latest .

# 2. Tag for Docker Hub
# Replace 'markgeorge10' with your Docker Hub username if different
docker tag shopify-ai-concierge-backend:latest markgeorge10/shopify-ai-concierge-backend:latest

# 3. Push to Docker Hub
docker push mfahim23/shopify-ai-concierge-backend:latest

# 4. Deploy to Google Cloud Run
# Assumes you have gcloud CLI installed and authenticated
gcloud run deploy shopify-concierge-api `
    --image docker.io/mfahim23/shopify-ai-concierge-backend:latest `
    --region us-central1 `
    --platform managed `
    --allow-unauthenticated `
    --port 8000
