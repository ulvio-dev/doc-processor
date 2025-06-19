#!/usr/bin/env python3
"""
Document to JSON Chunks Converter

This script takes a document (from a local path or URL) and converts it to JSON chunks
using the docling library. The chunks are saved to a specified output folder along with
a markdown version of the document.
"""

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

# Import docling for document processing
try:
    from docling.document_converter import DocumentConverter
    from docling.chunking import HybridChunker
except ImportError:
    print("Error: docling library not found. Please install it with 'pip install docling'")
    sys.exit(1)

def process_document(input_path: str, chunks_path: str, markdown_path: str):
    """
    Process a document from a local path or URL, chunk it, and save the chunks to a JSON file.
    Also saves a markdown version of the document.
    """
    try:
        # Initialize document converter and chunker
        doc_converter = DocumentConverter()
        hybrid_chunker = HybridChunker()
        
        # Convert document using Docling
        print(f"Loading document from: {input_path}")
        conv_result = doc_converter.convert(input_path)
        docling_doc = conv_result.document

        # Save markdown version of the document
        chunks_path_save = Path(chunks_path)
        markdown_path_save = Path(markdown_path)

        print(f"Saving markdown version to: {markdown_path_save}")
        docling_doc.save_as_markdown(filename=markdown_path_save)
        
        # Perform hierarchical chunking
        print("Chunking document...")
        chunks =list(hybrid_chunker.chunk(docling_doc))
        
        # Extract chunk texts as an array of strings
        chunk_texts = [chunk.text for chunk in chunks]
        
        # Save chunks to the output path
        print(f"Saving {len(chunk_texts)} chunks to: {chunks_path_save}")
        with open(chunks_path_save, 'w', encoding='utf-8') as f:
            json.dump(chunk_texts, f, ensure_ascii=False, indent=2)
        
        print("Document processing completed successfully!")
        
    except Exception as e:
        print(f"Error processing document: {str(e)}")
        print("Stack trace:")
        traceback.print_exc()
        raise e

def main():
    """Parse command line arguments and process the document."""
    parser = argparse.ArgumentParser(description='Convert a document to JSON chunks using docling.')
    parser.add_argument('input_path', help='Path or URL to the document')
    parser.add_argument('chunks_path', help='Path to save the JSON chunks file')
    parser.add_argument('markdown_path', help='Path to save the markdown file')
    
    args = parser.parse_args()
    
    # Check if input path exists (if it's a local file)
    if not args.input_path.startswith(('http://', 'https://')):
        if not os.path.exists(args.input_path):
            print(f"Error: Input file '{args.input_path}' does not exist.")
            sys.exit(1)
    
    # Process the document
    process_document(args.input_path, args.chunks_path, args.markdown_path)


if __name__ == "__main__":
    main()