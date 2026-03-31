import chromadb
from chromadb.config import Settings
import ollama
chroma_client = chromadb.PersistentClient(path = "./chroma_db")

# Create or get collection
collection = chroma_client.get_or_create_collection(
    name="complaints",
    metadata={"description": "Complaint embeddings for RAG"}  
)

def get_embedding(text: str) -> list[float]:
      response = ollama.embeddings(model="nomic-embed-text",    
  prompt=text)
      return response["embedding"]

def store_in_chromadb(complaint_id: str, text: str, metadata: dict):
      embedding = get_embedding(text)
      # Convert all metadata values to strings for ChromaDB compatibility
      string_metadata = {k: str(v) if v is not None else "" for k, v in metadata.items()}
      collection.add(
          ids=[complaint_id],
          embeddings=[embedding],
          documents=[text],
          metadatas=[string_metadata]
      )

def upsert_in_chromadb(complaint_id: str, text: str, metadata: dict):
      """
      Update an existing ChromaDB entry by deleting and re-adding.
      ChromaDB has no in-place update — this handles it cleanly.
      """
      existing = collection.get(ids=[complaint_id])
      if existing and existing.get("ids") and complaint_id in existing["ids"]:
          collection.delete(ids=[complaint_id])
      embedding = get_embedding(text)
      # Convert all metadata values to strings for ChromaDB compatibility
      string_metadata = {k: str(v) if v is not None else "" for k, v in metadata.items()}
      collection.add(
          ids=[complaint_id],
          embeddings=[embedding],
          documents=[text],
          metadatas=[string_metadata]
      )

def retrieve_complaints(query: str, top_k: int = 5) -> dict:
    """
    Search ChromaDB for complaints relevant to the query.
    Uses get_embedding to embed the query, then searches via query_embeddings.
    """
    query_embedding = get_embedding(query)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
    return results