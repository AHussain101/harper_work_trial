#!/usr/bin/env python3
"""
Name Registry: Qdrant-powered semantic search for company names and descriptions.

Provides fast lookup of accounts by company name or description using vector embeddings.
"""

import logging
import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Constants
COLLECTION_NAME = "account_names"
DESCRIPTIONS_COLLECTION_NAME = "account_descriptions"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536


class NameRegistry:
    """
    Manages account name embeddings in Qdrant for semantic search.
    
    Usage:
        registry = NameRegistry()
        registry.upsert_account("29042", "Maple Stoneworks", "mem/accounts/29042")
        results = registry.search("Maple Stone")
    """
    
    def __init__(
        self,
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        openai_api_key: Optional[str] = None
    ):
        """
        Initialize the name registry.
        
        Args:
            qdrant_host: Qdrant server host
            qdrant_port: Qdrant server port
            openai_api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        # Initialize Qdrant client
        self.qdrant = QdrantClient(host=qdrant_host, port=qdrant_port)
        
        # Initialize OpenAI client (check both common key names)
        api_key = openai_api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPEN_AI_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY or OPEN_AI_KEY not found in environment or constructor")
        self.openai = OpenAI(api_key=api_key)
        
        # Ensure collection exists
        self._ensure_collection()
    
    def _ensure_collection(self) -> None:
        """Create the collections if they don't exist."""
        collections = self.qdrant.get_collections().collections
        collection_names = [c.name for c in collections]
        
        if COLLECTION_NAME not in collection_names:
            logger.info(f"Creating collection: {COLLECTION_NAME}")
            self.qdrant.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIMENSION,
                    distance=Distance.COSINE
                )
            )
        
        if DESCRIPTIONS_COLLECTION_NAME not in collection_names:
            logger.info(f"Creating collection: {DESCRIPTIONS_COLLECTION_NAME}")
            self.qdrant.create_collection(
                collection_name=DESCRIPTIONS_COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIMENSION,
                    distance=Distance.COSINE
                )
            )
    
    def _embed(self, text: str) -> list[float]:
        """
        Generate embedding for text using OpenAI.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector as list of floats
        """
        response = self.openai.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text
        )
        return response.data[0].embedding
    
    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in a single API call.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        # OpenAI supports up to 2048 inputs per request
        batch_size = 2048
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = self.openai.embeddings.create(
                model=EMBEDDING_MODEL,
                input=batch
            )
            # Sort by index to maintain order
            sorted_data = sorted(response.data, key=lambda x: x.index)
            all_embeddings.extend([d.embedding for d in sorted_data])
        
        return all_embeddings
    
    def upsert_account(
        self,
        account_id: str,
        name: str,
        directory_path: str
    ) -> None:
        """
        Add or update an account in the registry.
        
        Args:
            account_id: Unique account identifier
            name: Company name to index
            directory_path: Path to account directory (e.g., "mem/accounts/29042")
        """
        # Generate embedding for the company name
        embedding = self._embed(name)
        
        # Use account_id as point ID (convert to int for Qdrant)
        point_id = int(account_id)
        
        # Upsert the point
        self.qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "account_id": account_id,
                        "name": name,
                        "directory_path": directory_path
                    }
                )
            ]
        )
        
        logger.debug(f"Upserted account {account_id}: {name}")
    
    def upsert_accounts_batch(
        self,
        accounts: list[dict]
    ) -> int:
        """
        Batch add or update multiple accounts in the registry.
        
        Much faster than calling upsert_account individually due to:
        - Single embedding API call for all names
        - Single Qdrant upsert operation
        
        Args:
            accounts: List of dicts with keys: account_id, name, directory_path
            
        Returns:
            Number of accounts upserted
        """
        if not accounts:
            return 0
        
        # Extract names for batch embedding
        names = [acc["name"] for acc in accounts]
        
        # Generate all embeddings in one API call
        embeddings = self._embed_batch(names)
        
        # Build points
        points = []
        for acc, embedding in zip(accounts, embeddings):
            point_id = int(acc["account_id"])
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "account_id": acc["account_id"],
                        "name": acc["name"],
                        "directory_path": acc["directory_path"]
                    }
                )
            )
        
        # Batch upsert to Qdrant
        self.qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )
        
        logger.info(f"Batch upserted {len(points)} accounts to name registry")
        return len(points)
    
    def upsert_descriptions_batch(
        self,
        accounts: list[dict]
    ) -> int:
        """
        Batch add or update multiple account descriptions.
        
        Args:
            accounts: List of dicts with keys: account_id, name, description, directory_path
            
        Returns:
            Number of descriptions upserted
        """
        if not accounts:
            return 0
        
        # Extract descriptions for batch embedding
        descriptions = [acc["description"] for acc in accounts]
        
        # Generate all embeddings in one API call
        embeddings = self._embed_batch(descriptions)
        
        # Build points
        points = []
        for acc, embedding in zip(accounts, embeddings):
            point_id = int(acc["account_id"])
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "account_id": acc["account_id"],
                        "name": acc["name"],
                        "description": acc["description"],
                        "directory_path": acc["directory_path"]
                    }
                )
            )
        
        # Batch upsert to Qdrant
        self.qdrant.upsert(
            collection_name=DESCRIPTIONS_COLLECTION_NAME,
            points=points
        )
        
        logger.info(f"Batch upserted {len(points)} account descriptions")
        return len(points)
    
    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Search for accounts by name.
        
        Args:
            query: Company name to search for
            top_k: Number of results to return
            
        Returns:
            List of matching accounts with scores:
            [
                {
                    "account_id": "29042",
                    "name": "Maple Stoneworks",
                    "path": "mem/accounts/29042",
                    "score": 0.95
                },
                ...
            ]
        """
        # Generate embedding for query
        query_embedding = self._embed(query)
        
        # Search Qdrant using query_points (new API)
        results = self.qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=query_embedding,
            limit=top_k
        )
        
        # Format results
        matches = []
        for result in results.points:
            matches.append({
                "account_id": result.payload["account_id"],
                "name": result.payload["name"],
                "path": result.payload["directory_path"],
                "score": round(result.score, 3)
            })
        
        return matches
    
    def delete_account(self, account_id: str) -> None:
        """
        Remove an account from the registry.
        
        Args:
            account_id: Account to remove
        """
        point_id = int(account_id)
        self.qdrant.delete(
            collection_name=COLLECTION_NAME,
            points_selector=[point_id]
        )
        self.qdrant.delete(
            collection_name=DESCRIPTIONS_COLLECTION_NAME,
            points_selector=[point_id]
        )
        logger.debug(f"Deleted account {account_id}")
    
    def count(self) -> int:
        """Get the number of accounts in the registry."""
        info = self.qdrant.get_collection(COLLECTION_NAME)
        return info.points_count
    
    def clear_all(self) -> None:
        """
        Delete and recreate both collections.
        
        Use this before re-ingestion to ensure no stale references remain.
        """
        logger.info("Clearing all Qdrant collections...")
        
        # Delete collections if they exist
        try:
            self.qdrant.delete_collection(COLLECTION_NAME)
            logger.info(f"Deleted collection: {COLLECTION_NAME}")
        except Exception:
            pass  # Collection might not exist
        
        try:
            self.qdrant.delete_collection(DESCRIPTIONS_COLLECTION_NAME)
            logger.info(f"Deleted collection: {DESCRIPTIONS_COLLECTION_NAME}")
        except Exception:
            pass  # Collection might not exist
        
        # Recreate collections
        self._ensure_collection()
        logger.info("Collections recreated")
    
    def upsert_description(
        self,
        account_id: str,
        name: str,
        description: str,
        directory_path: str
    ) -> None:
        """
        Add or update an account description in the descriptions registry.
        
        Args:
            account_id: Unique account identifier
            name: Company name
            description: Rich searchable description (stage, location, industry, etc.)
            directory_path: Path to account directory (e.g., "mem/accounts/29042")
        """
        # Generate embedding for the description
        embedding = self._embed(description)
        
        # Use account_id as point ID (convert to int for Qdrant)
        point_id = int(account_id)
        
        # Upsert the point
        self.qdrant.upsert(
            collection_name=DESCRIPTIONS_COLLECTION_NAME,
            points=[
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "account_id": account_id,
                        "name": name,
                        "description": description,
                        "directory_path": directory_path
                    }
                )
            ]
        )
        
        logger.debug(f"Upserted description for account {account_id}: {name}")
    
    def search_descriptions(self, query: str, top_k: int = 10) -> list[dict]:
        """
        Search for accounts by description (stage, location, industry, etc.).
        
        Use for implicit account references, stage-based queries, location queries,
        or industry searches.
        
        Args:
            query: Search query describing what you're looking for
            top_k: Number of results to return
            
        Returns:
            List of matching accounts with scores:
            [
                {
                    "account_id": "29119",
                    "name": "Sunny Days Childcare",
                    "description": "Sunny Days Childcare | Stage: Application Received | ...",
                    "path": "mem/accounts/29119",
                    "score": 0.85
                },
                ...
            ]
        """
        # Generate embedding for query
        query_embedding = self._embed(query)
        
        # Search Qdrant descriptions collection
        results = self.qdrant.query_points(
            collection_name=DESCRIPTIONS_COLLECTION_NAME,
            query=query_embedding,
            limit=top_k
        )
        
        # Format results
        matches = []
        for result in results.points:
            matches.append({
                "account_id": result.payload["account_id"],
                "name": result.payload["name"],
                "description": result.payload["description"],
                "path": result.payload["directory_path"],
                "score": round(result.score, 3)
            })
        
        return matches
    
    def descriptions_count(self) -> int:
        """Get the number of account descriptions in the registry."""
        info = self.qdrant.get_collection(DESCRIPTIONS_COLLECTION_NAME)
        return info.points_count


def main():
    """CLI for testing the name registry."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test the name registry")
    parser.add_argument("action", choices=["search", "search_descriptions", "count", "clear"], help="Action to perform")
    parser.add_argument("--query", "-q", help="Search query")
    parser.add_argument("--top-k", "-k", type=int, default=5, help="Number of results")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    registry = NameRegistry()
    
    if args.action == "clear":
        print("Clearing all Qdrant collections...")
        registry.clear_all()
        print("Done. Collections have been cleared and recreated.")
        return
    
    if args.action == "search":
        if not args.query:
            print("Error: --query required for search")
            return
        
        results = registry.search(args.query, args.top_k)
        print(f"\nName search results for '{args.query}':")
        print("-" * 60)
        for r in results:
            print(f"  {r['score']:.3f}  {r['name']} ({r['account_id']})")
            print(f"         {r['path']}")
    
    elif args.action == "search_descriptions":
        if not args.query:
            print("Error: --query required for search_descriptions")
            return
        
        results = registry.search_descriptions(args.query, args.top_k)
        print(f"\nDescription search results for '{args.query}':")
        print("-" * 60)
        for r in results:
            print(f"  {r['score']:.3f}  {r['name']} ({r['account_id']})")
            print(f"         {r['description'][:80]}...")
            print(f"         {r['path']}")
            print()
    
    elif args.action == "count":
        names_count = registry.count()
        desc_count = registry.descriptions_count()
        print(f"Accounts in name registry: {names_count}")
        print(f"Accounts in descriptions registry: {desc_count}")


if __name__ == "__main__":
    main()
