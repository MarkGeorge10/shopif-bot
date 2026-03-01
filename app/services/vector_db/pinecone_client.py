import logging
from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import ServerlessSpec

from app.core.config import settings
from app.services.vector_db.embedding import embedding_service

logger = logging.getLogger(__name__)

class PineconeClient:
    def __init__(self):
        self.api_key = settings.PINECONE_API_KEY
        self.index_name = settings.PINECONE_INDEX_NAME
        self.pc = None
        self.index = None
        self.dimension = embedding_service.DIMENSION

    def initialize(self):
        if not self.api_key or not self.index_name:
            logger.warning("Pinecone API key or Index Name not provided. Pinecone client will remain inactive.")
            return

        logger.info(f"Initializing Pinecone client (grpc) for index '{self.index_name}'...")
        self.pc = Pinecone(api_key=self.api_key)

        # Check if index exists, and create it dynamically matching our Embedding dimension
        existing_indexes = [index_info["name"] for index_info in self.pc.list_indexes()]

        if self.index_name not in existing_indexes:
            logger.info(f"Creating missing Pinecone Serverless index '{self.index_name}' (dim={self.dimension})...")
            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud=settings.PINECONE_CLOUD,
                    region=settings.PINECONE_REGION
                )
            )

        self.index = self.pc.Index(self.index_name)
        logger.info("Pinecone client initialized successfully.")

    def get_store_namespace(self, store_id: str) -> str:
        """Returns the isolated Pinecone namespace for a specific store."""
        return f"{settings.PINECONE_NAMESPACE_PREFIX}{store_id}"

# Singleton instance
pinecone_client = PineconeClient()
