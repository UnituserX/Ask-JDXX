# --- START OF FILE app/services/memory_manager.py ---
import os
import logging
import time
import hashlib
from typing import List, Dict, Optional, Tuple, Union
from flask import current_app, has_app_context
import chromadb
from chromadb.utils import embedding_functions
from chromadb.config import Settings
import spacy
from collections import Counter

# --- Logging ---
log = logging.getLogger(__name__)

# --- Constants ---
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
COLLECTION_NAME_PREFIX = "user_memory_"
DEFAULT_STORAGE_PATH = "./user_memory_stores"
SPACY_MODEL_NAME = "en_core_web_sm"

# --- Singleton Patterns ---
_chroma_client = None
_embedding_function = None
_nlp = None # spaCy model

# --- Helper Functions ---
def get_persistent_storage_path() -> str:
    """Gets the configured persistent storage path, ensuring it's absolute."""
    default_path = os.path.abspath(DEFAULT_STORAGE_PATH)
    if has_app_context():
        path = current_app.config.get('USER_MEMORY_STORE_PATH', default_path)
    else:
        path = os.getenv('USER_MEMORY_STORE_PATH', default_path)
    return os.path.abspath(path)

def get_chroma_client(force_reload: bool = False):
    """Gets a singleton ChromaDB client instance."""
    global _chroma_client
    if _chroma_client is None or force_reload:
        if force_reload: log.info("Forcing reload of ChromaDB client.")
        try:
            storage_path = get_persistent_storage_path()
            os.makedirs(storage_path, exist_ok=True)
            log.info(f"Initializing ChromaDB client: {storage_path}")
            client_settings = Settings(
                chroma_db_impl="duckdb+parquet", persist_directory=storage_path,
                anonymized_telemetry=False, allow_reset=True
            )
            _chroma_client = chromadb.Client(client_settings)
            log.info("ChromaDB client initialized.")
        except Exception as e:
            log.exception(f"Failed to initialize ChromaDB client: {e}")
            _chroma_client = None
            raise RuntimeError("Could not initialize ChromaDB client") from e
    return _chroma_client

def _check_gpu_available() -> bool:
    """Simple check for PyTorch GPU availability."""
    try:
        import torch; return torch.cuda.is_available()
    except ImportError: return False
    except Exception: return False

def get_embedding_function(force_reload: bool = False):
    """Gets a singleton Sentence Transformer embedding function instance."""
    global _embedding_function
    if _embedding_function is None or force_reload:
        if force_reload: log.info("Forcing reload of embedding model.")
        try:
            model_name = os.getenv("EMBEDDING_MODEL") # Env var takes precedence
            if not model_name and has_app_context():
                model_name = current_app.config.get('EMBEDDING_MODEL', DEFAULT_EMBEDDING_MODEL)
            elif not model_name: model_name = DEFAULT_EMBEDDING_MODEL

            log.info(f"Loading ST embedding model: {model_name}")
            start_time = time.time()
            device = "cuda" if _check_gpu_available() else "cpu"
            log.info(f"Using device: {device} for embeddings.")
            _embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=model_name, device=device
            )
            duration = time.time() - start_time
            log.info(f"Embedding model '{model_name}' loaded in {duration:.2f}s.")
        except ImportError: log.exception("Install sentence-transformers & torch/tensorflow"); _embedding_function=None; raise RuntimeError("Sentence Transformers library not found.") from ImportError
        except Exception as e: log.exception(f"Failed to load embedding model '{model_name}': {e}"); _embedding_function=None; raise RuntimeError(f"Could not load embedding model: {model_name}") from e
    return _embedding_function

def get_nlp_model():
    """Loads the spaCy NLP model."""
    global _nlp
    if _nlp is None:
        try:
            log.info(f"Loading spaCy model: {SPACY_MODEL_NAME}")
            _nlp = spacy.load(SPACY_MODEL_NAME)
            log.info("spaCy model loaded successfully.")
        except OSError: log.error(f"spaCy model '{SPACY_MODEL_NAME}' not found. Download: python -m spacy download {SPACY_MODEL_NAME}"); raise RuntimeError(f"spaCy model '{SPACY_MODEL_NAME}' not found.")
        except Exception as e: log.exception(f"Failed to load spaCy model: {e}"); raise RuntimeError("Could not load spaCy model.")
    return _nlp

def extract_keywords(text: str, max_keywords: int = 7) -> List[str]:
    """Extracts potential keywords (nouns, proper nouns) from text using spaCy."""
    keywords = []
    if not text or not isinstance(text, str): return keywords
    try:
        nlp = get_nlp_model()
        doc = nlp(text[:10000].lower()) # Limit length, process lowercased
        possible_keywords = [
            token.lemma_ for token in doc
            if not token.is_stop and not token.is_punct and not token.is_space
            and token.pos_ in ["NOUN", "PROPN"] and len(token.lemma_) > 2
        ]
        if not possible_keywords: return []
        keyword_counts = Counter(possible_keywords)
        keywords = [kw for kw, count in keyword_counts.most_common(max_keywords)]
    except Exception as e: log.error(f"Failed to extract keywords: {e}", exc_info=False)
    return keywords

def _get_user_collection_name(user_id: int) -> str:
    return f"{COLLECTION_NAME_PREFIX}{user_id}"

def _generate_doc_id(text: str, timestamp: float) -> str:
    hasher = hashlib.sha1()
    hasher.update(text.encode('utf-8', errors='ignore'))
    hasher.update(str(timestamp).encode('utf-8'))
    return hasher.hexdigest()[:20]

def get_or_create_user_collection(user_id: int) -> Optional['chromadb.Collection']:
    """Gets or creates a ChromaDB collection for a specific user."""
    try:
        client = get_chroma_client()
        embed_func = get_embedding_function()
        if not embed_func: raise RuntimeError("Embedding function failed to initialize.")
        collection_name = _get_user_collection_name(user_id)
        collection = client.get_or_create_collection(
            name=collection_name, embedding_function=embed_func,
            metadata={"hnsw:space": "cosine"}
        )
        return collection
    except RuntimeError as e: log.error(f"Cannot get/create collection for user {user_id}: {e}"); return None
    except Exception as e: log.exception(f"Failed to get/create collection for user {user_id}: {e}"); return None

def add_memory(user_id: int, text: str, metadata: Optional[Dict[str, Union[str, int, float, bool]]] = None) -> bool:
    """Adds a text snippet to the user's memory."""
    if not text or not isinstance(text, str) or not text.strip():
        log.warning(f"User {user_id}: Attempted to add empty/invalid memory text."); return False
    collection = get_or_create_user_collection(user_id)
    if not collection: log.error(f"User {user_id}: Cannot add memory, failed to get collection."); return False

    try:
        current_time = time.time()
        doc_id = _generate_doc_id(text, current_time)
        doc_metadata = {"timestamp": current_time}
        if metadata:
            for key, value in metadata.items():
                if isinstance(value, (str, int, float, bool)): doc_metadata[key] = value
                elif value is not None: doc_metadata[key] = str(value) # Convert others

        keywords = extract_keywords(text)
        if keywords: doc_metadata["keywords"] = ",".join(keywords) # Store as string

        collection.add(documents=[text], metadatas=[doc_metadata], ids=[doc_id])

        # Touch modification timestamp file
        storage_path = get_persistent_storage_path()
        user_dir_path = os.path.join(storage_path, f"user_{user_id}")
        mod_file_path = os.path.join(user_dir_path, '.last_modified')
        try:
            os.makedirs(user_dir_path, exist_ok=True)
            with open(mod_file_path, 'w') as f: f.write(str(current_time))
        except OSError as e: log.error(f"User {user_id}: Failed to update mod file '{mod_file_path}': {e}")

        log.info(f"User {user_id}: Added memory ID {doc_id}.")
        return True
    except Exception as e: log.exception(f"User {user_id}: Failed to add memory: {e}"); return False

def retrieve_memories(user_id: int, query_text: str, n_results: int = 5, filter_metadata: Optional[Dict] = None, require_keywords: bool = False) -> List[Tuple[str, float]]:
    """Retrieves relevant memories, optionally filtering by keywords."""
    memories = []
    if not query_text or not isinstance(query_text, str) or not query_text.strip(): return memories
    n_results = max(1, min(n_results, 50))
    collection = get_or_create_user_collection(user_id)
    if not collection: return memories

    try:
        count = collection.count()
        if count == 0: return memories

        final_filter = filter_metadata
        query_keywords = []
        if require_keywords:
            query_keywords = extract_keywords(query_text, max_keywords=5)
            if query_keywords:
                keyword_filter = {"$or": [{"keywords": {"$contains": kw}} for kw in query_keywords]}
                if final_filter: final_filter = {"$and": [final_filter, keyword_filter]}
                else: final_filter = keyword_filter

        results = collection.query(
            query_texts=[query_text], n_results=min(n_results, count),
            where=final_filter, include=['documents', 'distances']
        )

        documents = results.get('documents', [[]])[0]
        distances = results.get('distances', [[]])[0]
        if documents and distances and len(documents) == len(distances):
            valid_results = [(doc, dist) for doc, dist in zip(documents, distances) if dist is not None]
            memories = sorted(valid_results, key=lambda item: item[1])
            log.info(f"User {user_id}: Retrieved {len(memories)} memories (keywords: {bool(query_keywords)}).")
        elif documents: memories = [(doc, 0.0) for doc in documents] # Fallback

        return memories
    except Exception as e: log.exception(f"User {user_id}: Failed to retrieve memories: {e}"); return []

def get_all_memories(user_id: int, limit: int = 100, offset: int = 0) -> List[Dict]:
    """Retrieves all memories with metadata for history (limited, sorted by timestamp)."""
    memories = []
    collection = get_or_create_user_collection(user_id)
    if not collection: return memories
    try:
        count = collection.count()
        if count == 0: return memories
        fetch_limit = limit + offset if offset > 0 else limit # Fetch batch for sorting
        fetch_limit = min(fetch_limit, count) # Don't exceed total count

        results = collection.get(limit=fetch_limit, include=['metadatas', 'documents'])
        ids, documents, metadatas = results['ids'], results['documents'], results['metadatas']
        if not ids: return memories

        for i in range(len(ids)):
            if i < len(documents) and i < len(metadatas) and metadatas[i] is not None:
                memories.append({
                    "id": ids[i], "text": documents[i], "metadata": metadatas[i],
                    "timestamp": float(metadatas[i].get("timestamp", 0)) })

        memories.sort(key=lambda item: item.get('timestamp', 0), reverse=True)
        paginated_memories = memories[offset:offset + limit] # Slice *after* sorting
        log.info(f"User {user_id}: Retrieved {len(paginated_memories)} memories for history (offset={offset}).")
        return paginated_memories
    except Exception as e: log.exception(f"User {user_id}: Failed to retrieve all memories: {e}"); return []

def get_memory_count(user_id: int) -> int:
    """Gets the total number of items in a user's memory collection."""
    collection = get_or_create_user_collection(user_id)
    if not collection: return 0
    try: return collection.count()
    except Exception as e: log.exception(f"User {user_id}: Failed to get count: {e}"); return 0

def clear_user_memory(user_id: int) -> bool:
    """Deletes the entire memory collection for a user."""
    try:
        client = get_chroma_client()
        collection_name = _get_user_collection_name(user_id)
        log.warning(f"User {user_id}: Attempting delete collection '{collection_name}'")
        try:
            client.delete_collection(name=collection_name)
            log.info(f"User {user_id}: Deleted collection '{collection_name}'.")
            # Remove mod file
            storage_path = get_persistent_storage_path()
            mod_file_path = os.path.join(storage_path, f"user_{user_id}", '.last_modified')
            try:
                if os.path.exists(mod_file_path): os.remove(mod_file_path)
            except OSError as e: log.error(f"User {user_id}: Failed to remove mod file: {e}")
            return True
        except ValueError as ve: # Handle collection not found error
            if "does not exist" in str(ve): log.info(f"User {user_id}: Collection '{collection_name}' doesn't exist."); return True
            else: raise
        except Exception as del_e: log.exception(f"User {user_id}: Failed deleting collection '{collection_name}': {del_e}"); return False
    except RuntimeError: return False # Client init error
    except Exception as e: log.exception(f"User {user_id}: Failed pre-deletion step: {e}"); return False
# --- END OF FILE app/services/memory_manager.py ---