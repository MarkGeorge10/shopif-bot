import pytest
import numpy as np
from app.services.vector_db.embedding import MultimodalEmbeddingService

def test_combine_vectors_basic():
    # Setup mock vectors 
    img_vec = [1.0, 0.0, 0.0]
    txt_vec = [0.0, 1.0, 0.0]
    
    # Intentionally avoid initializing model weights for the test
    service = MultimodalEmbeddingService()
    service.dimension = 3
    
    # Run the function
    # L2 norm of [0.7, 0.3, 0.0] -> sqrt(0.49 + 0.09) = sqrt(0.58) = 0.7615
    # combined = [0.7 / 0.7615, 0.3 / 0.7615, 0.0] = [ 0.919, 0.394, 0.0 ] 
    combined = service.combine_vectors(img_vec, txt_vec, w_img=0.7, w_txt=0.3)
    
    assert len(combined) == 3
    assert abs(combined[0] - 0.919) < 0.01
    assert abs(combined[1] - 0.394) < 0.01
    assert combined[2] == 0.0
    
    # Ensure it's perfectly L2 normalized
    norm = np.linalg.norm(combined)
    assert abs(norm - 1.0) < 0.0001
    

def test_combine_vectors_empty():
    service = MultimodalEmbeddingService()
    
    # One empty
    img_vec = [1.0, 0.0, 0.0]
    combined = service.combine_vectors(img_vec, [], w_img=0.7, w_txt=0.3)
    assert combined == img_vec # Returns normalized pure image 
    
    # Both empty
    assert service.combine_vectors([], []) == []

