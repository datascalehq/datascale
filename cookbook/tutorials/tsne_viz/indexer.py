#!/usr/bin/env python3
"""
Text File Indexer for Embedding Generation

This script:
1. Finds all files with specified extensions in the given directory
2. Splits them into chunks using RecursiveCharacterTextSplitter
3. Generates embeddings using Gemini
4. Saves the embeddings to a JSON file
"""

import os
import sys
import glob
import time
import argparse
import json
from typing import List, Dict, Any
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai.types import EmbedContentConfig
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Load environment variables
load_dotenv()

# Configuration
CHUNK_SIZE         = 600
CHUNK_OVERLAP      = 200
EMBEDDING_SIZE     = 768
BATCH_SIZE         = 20   # Process files in batches to avoid rate limits
GEMINI_BATCH_LIMIT = 100  # Maximum batch size for Gemini embedding API
OUTPUT_JSON_FILE   = "embeddings.json"

# Initialize Gemini client
model_id = os.getenv("GEMINI_EMBEDDING_ID", "text-embedding-004")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def read_text_file(file_path: str) -> str:
    """
    Read a text file and return its contents

    Args:
        file_path: Path to the text file

    Returns:
        String content of the text file
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        return ""

def split_text(text: str, file_path: str) -> List[Dict[str, Any]]:
    """
    Split text into chunks and prepare for embedding

    Args:
        text: Text content to split
        file_path: Original file path for tracking

    Returns:
        List of dictionaries with chunk information
    """
    # Initialize the text splitter
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP
    )

    # Split the text into chunks
    chunks = text_splitter.split_text(text)

    # Get the relative file path for the file_id
    file_id = os.path.relpath(file_path).replace("\\", "/")

    # Create a list of chunk dictionaries
    chunk_dicts = []
    for i, chunk_text in enumerate(chunks):
        # Get start position (approximate)
        start_pos = i * (CHUNK_SIZE - CHUNK_OVERLAP) if i > 0 else 0
        end_pos = start_pos + len(chunk_text)

        chunk_id = f"{file_id}_{start_pos}-{end_pos}"

        chunk_dicts.append({
            "id"       : chunk_id,
            "file_id"  : file_id,
            "content"  : chunk_text,
            "start_pos": start_pos,
            "end_pos"  : end_pos
        })

    return chunk_dicts

def embed_content(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Generate embeddings for a list of text chunks

    Args:
        chunks: List of chunk dictionaries with content

    Returns:
        Chunks with embeddings added
    """
    # Process in batches of GEMINI_BATCH_LIMIT to avoid API limitations
    all_chunks_with_embeddings = []

    for i in range(0, len(chunks), GEMINI_BATCH_LIMIT):
        batch = chunks[i:i + GEMINI_BATCH_LIMIT]
        print(f"Processing embedding batch {i//GEMINI_BATCH_LIMIT + 1} ({len(batch)} chunks)...")

        # Extract text content from chunks
        texts = [chunk["content"] for chunk in batch]

        try:
            # Generate embeddings
            response = client.models.embed_content(
                model=model_id,
                contents=texts,
                config=EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=EMBEDDING_SIZE
                )
            )

            # Add embeddings to chunks
            for j, embedding in enumerate(response.embeddings):
                batch[j]["embedding"] = embedding.values

            all_chunks_with_embeddings.extend(batch)

        except Exception as e:
            print(f"Error generating embeddings for batch {i//GEMINI_BATCH_LIMIT + 1}: {e}")
            # Add chunks without embeddings
            for chunk in batch:
                chunk["embedding"] = []
                all_chunks_with_embeddings.append(chunk)

        # Add a small delay between batches to avoid rate limits
        if i + GEMINI_BATCH_LIMIT < len(chunks):
            time.sleep(0.5)

    return all_chunks_with_embeddings

def index_markdown_files(directory: str, file_types: List[str], dry_run: bool = False) -> Dict[str, Any]:
    """
    Find all specified file types in a directory and index them

    Args:
        directory: Path to directory to scan for files
        file_types: List of file extensions to index (e.g., ['.md', '.txt'])
        dry_run: If True, don't actually upload to Supabase

    Returns:
        Dictionary with statistics about the indexing process
    """
    start_time = time.time()
    all_processed_chunks = []
    all_found_files = []

    # Find all specified file types
    for file_type in file_types:
        # Ensure the file type starts with a dot
        if not file_type.startswith('.'):
            file_type = '.' + file_type
        found = glob.glob(f"{directory}/**/*{file_type}", recursive=True)
        all_found_files.extend(found)
        print(f"Found {len(found)} files with extension {file_type}")

    if not all_found_files:
        return {
            "status": "error",
            "message": f"No files with specified extensions ({', '.join(file_types)}) found in {directory}"
        }

    print(f"Found a total of {len(all_found_files)} files to process in {directory}")

    # Statistics
    stats = {
        "files_processed": 0,
        "files_failed"   : 0,
        "chunks_created" : 0,
        "chunks_indexed" : 0,
        "processing_time": 0
    }

    # Process files in batches
    for i in range(0, len(all_found_files), BATCH_SIZE):
        batch = all_found_files[i:i + BATCH_SIZE]

        all_chunks = []

        # Process each file in the batch
        for file_path in batch:
            try:
                # Read the file
                content = read_text_file(file_path)
                if not content:
                    stats["files_failed"] += 1
                    continue

                # Split the content into chunks
                chunks = split_text(content, file_path)

                # Add to the list of all chunks
                all_chunks.extend(chunks)

                # Update statistics
                stats["files_processed"] += 1
                stats["chunks_created"] += len(chunks)

                print(f"Processed {file_path} - {len(chunks)} chunks")

            except Exception as e:
                print(f"Error processing file {file_path}: {e}")
                stats["files_failed"] += 1

        # Generate embeddings for all chunks in the batch
        if all_chunks:
            chunks_with_embeddings = embed_content(all_chunks)

            # Filter out chunks without embeddings
            valid_chunks = [chunk for chunk in chunks_with_embeddings if chunk.get("embedding")]

            # Append valid chunks to the main list
            all_processed_chunks.extend(valid_chunks)
            print(f"Added {len(valid_chunks)} valid chunks from batch {i//BATCH_SIZE + 1}")

        # Add a small delay between batches to avoid rate limits
        if i + BATCH_SIZE < len(all_found_files):
            time.sleep(1)

    # Calculate total processing time
    stats["processing_time"] = round(time.time() - start_time, 2)
    stats["chunks_indexed"] = len(all_processed_chunks)

    # Write embeddings to JSON file if not dry run
    if not dry_run and all_processed_chunks:
        try:
            with open(OUTPUT_JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump(all_processed_chunks, f, indent=2)
            message = f"Processed {stats['files_processed']} files and saved {stats['chunks_indexed']} chunks to {OUTPUT_JSON_FILE} in {stats['processing_time']} seconds"
            print(f"Successfully wrote embeddings to {OUTPUT_JSON_FILE}")
        except Exception as e:
            print(f"Error writing embeddings to {OUTPUT_JSON_FILE}: {e}")
            return {
                "status": "error",
                "message": f"Failed to write embeddings to {OUTPUT_JSON_FILE}: {e}",
                "stats": stats
            }
    elif dry_run:
        message = f"Dry run complete. Would have saved {stats['chunks_indexed']} chunks to {OUTPUT_JSON_FILE}. Processed {stats['files_processed']} files in {stats['processing_time']} seconds"
        print(message)
    else:
        message = f"No valid embeddings generated. Processed {stats['files_processed']} files in {stats['processing_time']} seconds"
        print(message)

    return {
        "status": "success",
        "message": message,
        "stats": stats
    }

def main():
    """Main function to parse arguments and run the indexer"""
    parser = argparse.ArgumentParser(description="Index text files for vector search")
    parser.add_argument("--directory", nargs="?", default=".", help="Directory to scan for files (default: current directory)")
    parser.add_argument("--file-types", nargs='+', default=['.md'], help="List of file extensions to index (default: .md), e.g., --file-types .md .txt .rst")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without writing embeddings to file")

    args = parser.parse_args()

    # Validate environment variables
    if not os.getenv("GEMINI_API_KEY"):
        print("Error: GEMINI_API_KEY environment variable must be set")
        sys.exit(1)

    # Run the indexer
    result = index_markdown_files(args.directory, args.file_types, args.dry_run)

    # Print the result
    if result["status"] == "success":
        print(f"\nSuccess: {result['message']}")
        print(f"Statistics:")
        for key, value in result["stats"].items():
            print(f"  {key}: {value}")
    else:
        print(f"\nError: {result['message']}")
        sys.exit(1)

if __name__ == "__main__":
    main()
