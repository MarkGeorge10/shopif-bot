import pandas as pd
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
import time
import requests
from io import BytesIO
from PIL import Image

# Load data from previous step
df = pd.read_csv("shopify_products_prep.csv")
print(f"Loaded {len(df)} products.")

# Initialize Multimodal Sentence Transformer
print("Loading CLIP multimodal model...")
model = SentenceTransformer('clip-ViT-B-32')
print("Model loaded!")

def load_image_from_url(url):
    try:
        r = requests.get(url, timeout=5)
        img = Image.open(BytesIO(r.content)).convert("RGB")
        img.thumbnail((300, 300)) # resize to save memory
        return img
    except Exception as e:
        return None

# We need separate lists for vectors, but we'll put them in the same FAISS index for fun, 
# or just separate indexes. For simplicity, we'll make ONE unified index 
# and track which vector ID belongs to what (text vs image)

all_embeddings = []
metadata_map = [] # stores {"type": "text"|"image", "product_index": i}

print(f"Generating embeddings for {len(df)} products (Text & Image)...")
start_time = time.time()

for i, row in df.iterrows():
    # 1. Embed Text
    text = row["embedding_text"]
    text_emb = model.encode([text])[0]
    all_embeddings.append(text_emb)
    metadata_map.append({"type": "text", "idx": i})
    
    # 2. Embed Image
    if pd.notna(row["image_url"]):
        img = load_image_from_url(row["image_url"])
        if img:
            img_emb = model.encode([img])[0]
            all_embeddings.append(img_emb)
            metadata_map.append({"type": "image", "idx": i})
            
    if i % 10 == 0 and i > 0:
        print(f"Processed {i} products...")

embeddings_array = np.array(all_embeddings).astype("float32")
dimension = embeddings_array.shape[1]

print(f"Done in {time.time() - start_time:.2f} seconds.")
print(f"Total Vectors: {len(embeddings_array)} (Dimension: {dimension})")

# Create Index
index = faiss.IndexFlatL2(dimension)
index.add(embeddings_array)
print(f"FAISS Index contains {index.ntotal} vectors.")

# --- NEW: Save the index and metadata to disk ---
faiss.write_index(index, "faiss_index.bin")
pd.to_pickle(metadata_map, "faiss_metadata.pkl")
print("Saved FAISS index to 'faiss_index.bin' and metadata to 'faiss_metadata.pkl'!")

def search_faiss(query_emb, k=5, target_type=None):
    # We must fetch way more results if we want to filter by target_type (e.g., finding the top 3 images out of a mixed text/image index)
    search_depth = 50 if target_type else k
    distances, indices = index.search(query_emb, search_depth)
    
    results = []
    seen_products = set()
    
    for i, idx in enumerate(indices[0]):
        if idx != -1:
            meta = metadata_map[idx]
            
            # Filter by exactly what we want to find
            if target_type and meta["type"] != target_type:
                continue
                
            p_idx = meta["idx"]
            
            # Deduplicate items we've already matched
            if p_idx in seen_products:
                continue
            seen_products.add(p_idx)
            
            row = df.iloc[p_idx]
            results.append({
                "score": float(distances[0][i]),
                "match_type": meta["type"], 
                "title": row["title"],
            })
            
            if len(results) == k:
                break
                
    return pd.DataFrame(results)

print("\n" + "="*50)
print("TEST 1: TEXT-to-TEXT Search (Like before)")
# We embed text, and strictly search for Product Text vectors
q_text = model.encode(["something cozy for winter"]).astype("float32")
res1 = search_faiss(q_text, target_type="text", k=3)
print(res1[["score", "title"]])


print("\n" + "="*50)
print("TEST 2: TEXT-to-IMAGE Search")
# We embed text, but strictly ask FAISS "Find me Product Image vectors that look like this idea"
q_text2 = model.encode(["A striped pattern"]).astype("float32")
res2 = search_faiss(q_text2, target_type="image", k=3)
if not res2.empty:
    print(res2[["score", "title", "match_type"]])
else:
    print("No matches found.")


print("\n" + "="*50)
print("TEST 3: IMAGE-to-TEXT Search")
# We pretend the user uploaded a photo of a backpack, and we search for Text descriptions
# For this test, we'll just grab the 5th product's image from the dataset as our "Upload"
test_img_url = df.iloc[5]["image_url"]
if pd.notna(test_img_url):
    test_img = load_image_from_url(test_img_url)
    if test_img:
        q_img = model.encode([test_img]).astype("float32")
        print(f"(Uploaded Image of: {df.iloc[5]['title']})")
        res3 = search_faiss(q_img, target_type="text", k=3)
        if not res3.empty:
            print(res3[["score", "title", "match_type"]])
        else:
            print("No matches found.")
else:
    print("Could not run Test 3: No image found on test product.")


print("\n" + "="*50)
print("TEST 4: IMAGE + TEXT Search (Composite Query)")
# We take an image, and modify it with a text demand (e.g. "I want this, but in black")
if pd.notna(test_img_url):
    # test_img is already loaded from Test 3
    if test_img:
        text_modifier = "black color"
        print(f"(Uploaded Image of: {df.iloc[5]['title']} \n+ Text Modifier: '{text_modifier}')")
        
        # Generate vectors for both modalities
        q_img_vec = model.encode([test_img])[0]
        q_text_vec = model.encode([text_modifier])[0]
        
        # In CLIP, joining modalities is often as simple as averaging their vectors
        combined_vec = ((q_img_vec + q_text_vec) / 2.0).astype("float32")
        
        # Must be 2D array for FAISS
        combined_query = np.array([combined_vec])
        
        # Let's search the image catalog to find visually relevant products matching the new text constraints
        res4 = search_faiss(combined_query, target_type="image", k=3)
        if hasattr(res4, 'empty') and not res4.empty:
            print(res4[["score", "title", "match_type"]])
        else:
            print("No matches found.")
    else:
        print("Could not load image for Test 4.")
else:
    print("Could not run Test 4: No image found on test product.")
