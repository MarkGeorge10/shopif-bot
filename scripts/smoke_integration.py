import asyncio
import os
import argparse
import sys
from dotenv import load_dotenv

# Run setup
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

async def main():
    parser = argparse.ArgumentParser(description="Smoke test for RAG Phase 2 Integration")
    parser.add_argument("--test-embedding", action="store_true", help="Test the Multimodal Embedding Service")
    parser.add_argument("--test-celery", action="store_true", help="Send a mock indexing task to Celery")
    args = parser.parse_args()
    
    # Optional DB connection if needed in the future
    # from app.core.database import prisma
    # await prisma.connect()
    
    print("🚀 Starting RAG Phase 2 Smoke Tests 🚀")
    
    if args.test_embedding:
        print("\n[1] Testing MultimodalEmbeddingService...")
        os.environ["TOKENIZERS_PARALLELISM"] = "false" # Silence warnings
        
        try:
            from app.services.vector_db.embedding import embedding_service
            print("  -> Initialized CLIP model")
            txt_emb = embedding_service.embed_text("A red dress")
            print(f"  -> Generated Text Vector (dim: {len(txt_emb)})")
            
            # Using basic numpy math to mock the image vector
            import numpy as np
            mock_img_emb = np.random.rand(512).tolist()
            
            combined = embedding_service.combine_vectors(mock_img_emb, txt_emb, w_img=0.5, w_txt=0.5)
            print(f"  -> Combined Multimodal Vector successfully!")
            print("  -> [PASS] Embedding logic.")
        except Exception as e:
            print(f"  -> [FAIL] Embedding error: {e}")
            
    if args.test_celery:
        print("\n[2] Testing Celery Queue Connectivity...")
        try:
            from app.core.celery_app import celery_app
            
            # Inspect active nodes
            i = celery_app.control.inspect()
            stats = i.stats()
            if not stats:
                print("  -> [WARNING] No active Celery workers found! Please run `celery -A app.core.celery_app worker` in another terminal.")
            else:
                workers = list(stats.keys())
                print(f"  -> Found {len(workers)} active Celery worker(s): {workers}")
                
            print("  -> [PASS] Celery connectivity (Broker is reachable).")
        except Exception as e:
            print(f"  -> [FAIL] Celery connection error: {e}")
            
    print("\n✅ Smoke Tests Completed. Ensure you have Redis running and API Keys in your .env!")

if __name__ == "__main__":
    asyncio.run(main())
