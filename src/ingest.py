 
import argparse
import os
from dotenv import load_dotenv
from src.helper import run_full_ingestion

FLAG_FILE="data/ingestion_done.flag"
os.makedirs("data", exist_ok=True)
load_dotenv()


def main():
    parser=argparse.ArgumentParser(description="Medical Chatbot — Data Ingestion")
    parser.add_argument("--pdf",  type=str, default=None,help="Path to medical PDF book (optional)" )
    parser.add_argument("--book", type=str, default="Medical Textbook",help="Name of the book (for metadata)")
    parser.add_argument("--force", action="store_true", help="Force re-ingestion of all data")
    args=parser.parse_args()

    if os.path.exists(FLAG_FILE) and not args.force:
        print("Data ingestion already completed. Use --force to re-ingest.")
        return
    
    if args.force:
        print("Forcing re-ingestion of all data...")
        for f in ["data/who_diseases.json", "data/pdf_pages.json"]:
            if os.path.exists(f):
                os.remove(f)
            _clear_pinecone()
            
            if os.path.exists(FLAG_FILE):
                os.remove(FLAG_FILE)

    from src.helper import run_full_ingestion
    run_full_ingestion(pdf_path=args.pdf, book_name=args.book)


    from datetime import datetime
    with open(FLAG_FILE, "w") as f:
        f.write(f"Ingestion completed on {datetime.now().isoformat()}")
        if args.pdf:
            f.write(f" with PDF: {args.pdf} and book name: {args.book}")
        
    print(f"Flag saved to {FLAG_FILE}. Ingestion process completed.")


def _clear_pinecone():
    try:
        from pinecone import Pinecone
        pc=Pinecone(api_key=os.getenv("PINECONE_API_KEY"), environment=os.getenv("PINECONE_ENVIRONMENT"))
        index_name=os.getenv("PINECONE_INDEX_NAME","medical-chatbot")
        existing=[i.name for i in pc.list_indexes()]
        if index_name in existing:
            index=pc.Index(index_name)
            index.delete(delete_all=True)
            print(f"Deleting existing Pinecone index: {index_name}")
            pc.delete_index(index_name)

       
    except Exception as e:
        print(f"Error occurred while initializing Pinecone: {e}")
    

if __name__=="__main__":
    main()
