import logging
from typing import List

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

import logging
from typing import List
from PIL import Image
import numpy as np

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

class MultimodalEmbeddingService:
    """
    Phase 2: Multimodal (Text + Image) embeddings for production.
    Uses 'clip-ViT-B-32' to map both text and images into a shared 512-dimension space.
    Dimension: 512
    """
    MODEL_NAME = 'clip-ViT-B-32'
    DIMENSION = 512

    def __init__(self):
        logger.info(f"Loading multimodal embedding model {self.MODEL_NAME}...")
        self.model = SentenceTransformer(self.MODEL_NAME)
        logger.info("Multimodal embedding model loaded successfully.")

    def embed_text(self, text: str) -> List[float]:
        """Generate a float list embedding for a single text string."""
        return self.model.encode([text])[0].astype("float32").tolist()

    def embed_image(self, image: Image.Image) -> List[float]:
        """Generate a float list embedding for a PIL Image."""
        return self.model.encode([image])[0].astype("float32").tolist()

    def combine_vectors(
        self, 
        img_vec: List[float], 
        txt_vec: List[float], 
        w_img: float = 0.7, 
        w_txt: float = 0.3
    ) -> List[float]:
        """
        Combines an image vector and text vector using weighted addition, then 
        L2 normalizes the result so it retains parity in the cosine similarity space.
        """
        v_img = np.array(img_vec, dtype="float32")
        v_txt = np.array(txt_vec, dtype="float32")
        
        combined = (v_img * w_img) + (v_txt * w_txt)
        
        # L2 Normalization
        norm = np.linalg.norm(combined)
        if norm > 0:
            combined = combined / norm
            
        return combined.tolist()

# Singleton instance for the app
embedding_service = MultimodalEmbeddingService()
