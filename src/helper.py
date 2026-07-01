
import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from pinecone import Pinecone, ServerlessSpec
from langchain_pinecone import PineconeVectorStore
from langchain.schema import SystemMessage, HumanMessage
import fitz  
#change openapi to groq

from src.prompt import (
    SYSTEM_PROMPT,
    RAG_PROMPT_TEMPLATE,
    FALLBACK_PROMPT_TEMPLATE,
    SYMPTOM_CHECKER_PROMPT,
)


load_dotenv()


PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_ENV     = os.getenv("PINECONE_ENV", "us-east-1")
INDEX_NAME       = os.getenv("PINECONE_INDEX", "medical-chatbot")


EMBEDDING_MODEL  = "sentence-transformers/all-MiniLM-L6-v2"


# 0.68 means "68% similar — good enough to use"
SCORE_THRESHOLD  = 0.68


SCRAPE_HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; MedicalBot/1.0)"}


WHO_DATA_FILE    = "data/who_diseases.json"
PDF_DATA_FILE    = "data/pdf_pages.json"

# Create the data folder if it doesn't exist
os.makedirs("data", exist_ok=True)



def get_embeddings():
    try:
        import sentence_transformers
        print("DEBUG: sentence_transformers imported successfully!")
    except Exception as e:
        import traceback
        print("DEBUG: Failed to import sentence_transformers. Traceback:")
        traceback.print_exc()
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


def init_pinecone():
    pc = Pinecone(api_key=PINECONE_API_KEY)

    
    existing_indexes = [i.name for i in pc.list_indexes()]

    if INDEX_NAME not in existing_indexes:
        
        pc.create_index(
            name=INDEX_NAME,
            dimension=384,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region=PINECONE_ENV)
        )
        print(f"Created new Pinecone index: {INDEX_NAME}")
    else:
        print(f"Using existing Pinecone index: {INDEX_NAME}")


def get_vectorstore(embeddings=None):
    if embeddings is None:
        embeddings = get_embeddings()
    return PineconeVectorStore.from_existing_index(INDEX_NAME, embeddings)

from langchain_groq import ChatGroq
from dotenv import load_dotenv
from pydantic import SecretStr

load_dotenv()
GROQ_API_KEY=os.getenv("GROQ_API_KEY")
def get_llm():
    
    return ChatGroq(
        model="llama-3.1-8b-instant",  # use the instruct version for better answers
        temperature=0.2,  # 0 = more factual, 1 = more creative
        api_key=SecretStr(GROQ_API_KEY) if GROQ_API_KEY else None
    )

def get_who_disease_slugs():
    """
    Get the list of all disease page names from WHO website.

    A "slug" is the last part of a URL.
    Example URL: https://www.who.int/news-room/fact-sheets/detail/diabetes
    The slug is: diabetes

    This function visits WHO's fact-sheets page and collects
    all disease slugs automatically.
    """
    url = "https://www.who.int/news-room/fact-sheets"
    response = requests.get(url, headers=SCRAPE_HEADERS, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")

    slugs = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        # Only keep links that go to a fact sheet page
        if "/news-room/fact-sheets/detail/" in href:
            # Extract just the disease name from the URL
            slug = href.split("/news-room/fact-sheets/detail/")[-1]
            slug = slug.strip("/").split("?")[0]  # remove trailing slashes or query params
            if slug and slug not in slugs:
                slugs.append(slug)

    print(f"Found {len(slugs)} diseases on WHO website")
    return slugs

def scrape_who_page_sections(content_div):
    
    sections = []
    current_heading = "Overview"
    current_texts = []

    for element in content_div.find_all(["h2", "h3", "p", "ul", "ol"]):
        if element.name in ["h2", "h3"]:
            # We hit a new heading — save the previous section first
            if current_texts:
                sections.append({
                    "heading": current_heading,
                    "text": "\n".join(current_texts).strip()
                })
            # Start a new section
            current_heading = element.get_text(strip=True)
            current_texts = []
        else:
            # This is paragraph/list text — add it to current section
            text = element.get_text(separator=" ", strip=True)
            if text:
                current_texts.append(text)

    
    if current_texts:
        sections.append({
            "heading": current_heading,
            "text": "\n".join(current_texts).strip()
        })

    return sections

def scrape_one_who_disease(slug):
    
    url = f"https://www.who.int/news-room/fact-sheets/detail/{slug}"
    try:
        response = requests.get(url, headers=SCRAPE_HEADERS, timeout=15)

        # 404 means page not found
        if response.status_code == 404:
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        # The main content of WHO pages is inside this div
        content = (
            soup.find("article", {"class": "sf-detail-body-wrapper"})
            or soup.find("div", {"class": "content"})
        )
        if not content:
            return None

        # Get the disease title from the <h1> tag
        title_tag = soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else slug

        return {
            "slug": slug,
            "title": title,
            "url": url,
            "sections": scrape_who_page_sections(content)
        }

    except Exception as e:
        print(f"Failed to scrape {slug}: {e}")
        return None


def scrape_all_who_diseases():
    
    # If already scraped, load from file
    if os.path.exists(WHO_DATA_FILE):
        print(f"Loading WHO data from saved file: {WHO_DATA_FILE}")
        with open(WHO_DATA_FILE) as f:
            return json.load(f)

    # Otherwise scrape everything
    slugs = get_who_disease_slugs()
    results = []

    for i, slug in enumerate(slugs):
        print(f"[{i+1}/{len(slugs)}] Scraping: {slug}")
        data = scrape_one_who_disease(slug)

        if data:
            results.append(data)
            print(f"  Done: {data['title']}")

        # Save every 10 diseases in case something crashes
        if (i + 1) % 10 == 0:
            with open(WHO_DATA_FILE, "w") as f:
                json.dump(results, f, indent=2)
            print(f"  Progress saved ({len(results)} diseases so far)")

        # Wait 1.5 seconds between requests — don't overload WHO server
        time.sleep(1.5)

    # Final save
    with open(WHO_DATA_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nScraping complete — saved {len(results)} diseases")
    return results




def clean_pdf_text(text):
    text = re.sub(r'\n\s*\d+\s*\n', '\n', text)       # remove lone page numbers
    text = re.sub(r'\n{3,}', '\n\n', text)              # max 2 blank lines
    text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)      # fix "hyph-\nenation"
    return text.strip()


def is_chapter_heading(line):
    line = line.strip()
    if not line:
        return False
    if re.match(r'^(CHAPTER|SECTION|PART)\s+\d+', line, re.IGNORECASE):
        return True
    if line.isupper() and 5 < len(line) < 60:
        return True
    return False


def extract_text_from_pdf(pdf_path, book_name):
    
    # If already extracted, load from file
    if os.path.exists(PDF_DATA_FILE):
        print(f"Loading PDF data from saved file: {PDF_DATA_FILE}")
        with open(PDF_DATA_FILE) as f:
            return json.load(f)

    doc = fitz.open(pdf_path)
    pages_data = []
    current_chapter = "General"

    for page_num in range(len(doc)):
        page = doc[page_num]
        raw_text = page.get_text("text")
        if not isinstance(raw_text, str):
            raw_text = ""

        # Check if this page has real text or is a scanned image
        if len(raw_text.strip()) > 50:
            # Real text page — extract directly
            text = raw_text
            page_type = "digital"
        else:
            try:
                import pytesseract
                from PIL import Image
                import io
                # Convert the page to an image first
                pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                # Then read text from the image
                text = pytesseract.image_to_string(img)
                page_type = "scanned"
            except Exception:
                text = ""
                page_type = "scanned_failed"

        text = clean_pdf_text(text)

        # Check first few lines of this page for a chapter heading
        for line in text.split("\n")[:5]:
            if is_chapter_heading(line):
                current_chapter = line.strip()
                break

        pages_data.append({
            "page_number": page_num + 1,
            "text": text,
            "chapter": current_chapter,
            "page_type": page_type,
            "source": book_name
        })

        print(f"  Page {page_num+1}/{len(doc)} [{page_type}] — {current_chapter}")

    doc.close()

    # Save to file
    with open(PDF_DATA_FILE, "w") as f:
        json.dump(pages_data, f, indent=2)

    print(f"PDF extraction complete — {len(pages_data)} pages saved")
    return pages_data



def make_splitter():
    """
    Create a text splitter.
    chunk_size=400    → each piece is max 400 characters
    chunk_overlap=60  → each piece shares 60 chars with the next
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=400,
        chunk_overlap=60,
        separators=["\n\n", "\n", ". ", " "]  # prefer to split at paragraphs
    )


def who_data_to_chunks(who_data):
    splitter = make_splitter()
    all_chunks = []

    for disease in who_data:
        for section in disease.get("sections", []):

            # Skip sections that are too short to be useful
            if len(section["text"]) < 50:
                continue

            # Split this section into chunks
            text_chunks = splitter.split_text(section["text"])

            for chunk in text_chunks:
                all_chunks.append({
                    "text": chunk,
                    "metadata": {
                        "source":  "WHO",
                        "disease": disease["title"],
                        "section": section["heading"],
                        "url":     disease["url"]
                    }
                })

    print(f" WHO data → {len(all_chunks)} chunks total")
    return all_chunks


def pdf_data_to_chunks(pdf_data):
    
    splitter = make_splitter()
    all_chunks = []

    for page in pdf_data:
        if len(page.get("text", "")) < 50:
            continue

        text_chunks = splitter.split_text(page["text"])

        for chunk in text_chunks:
            all_chunks.append({
                "text": chunk,
                "metadata": {
                    "source":  page["source"],
                    "chapter": page["chapter"],
                    "page":    page["page_number"]
                }
            })

    print(f" PDF data → {len(all_chunks)} chunks total")
    return all_chunks


def store_chunks_in_pinecone(all_chunks, embeddings):
    
    batch_size = 100
    total = len(all_chunks)

    for i in range(0, total, batch_size):
        batch = all_chunks[i : i + batch_size]
        texts = [chunk["text"] for chunk in batch]
        metas = [chunk["metadata"] for chunk in batch]

        PineconeVectorStore.from_texts(
            texts=texts,
            embedding=embeddings,
            index_name=INDEX_NAME,
            metadatas=metas
        )

        stored_so_far = min(i + batch_size, total)
        print(f"Batch {i//batch_size + 1} stored ({stored_so_far}/{total} chunks)")

    print(f"\nAll {total} chunks stored in Pinecone!")


def run_full_ingestion(pdf_path=None, book_name=None):
    
    print("\n" + "="*50)
    print("  MEDICAL CHATBOT — DATA INGESTION")
    print("="*50)

    #step 1 
    init_pinecone()
    embeddings = get_embeddings()

    all_chunks = []

    # Step 2
    print("\n Step 2: Scraping WHO diseases...")
    who_data = scrape_all_who_diseases()
    all_chunks += who_data_to_chunks(who_data)

    # Step 3 (only if a PDF path was provided)
    if pdf_path and os.path.exists(pdf_path):
        print(f"\n📖 Step 3: Extracting PDF — {book_name}")
        pdf_data = extract_text_from_pdf(pdf_path, book_name or "Medical Textbook")
        all_chunks += pdf_data_to_chunks(pdf_data)
    else:
        print("\n Step 3: No PDF provided — skipping")

    # Step 4
    print(f"\n🚀 Step 4: Storing {len(all_chunks)} chunks in Pinecone...")
    store_chunks_in_pinecone(all_chunks, embeddings)

    print("\nDone! Your chatbot knowledge base is ready.\n")


def search_pinecone(query, vectorstore):
    
    try:
        # similarity_search_with_score returns list of (document, score)
        results = vectorstore.similarity_search_with_score(query, k=4)

        if not results:
            return None, None

        best_score = results[0][1]

        if best_score >= SCORE_THRESHOLD:
            # Combine top results into one context block
            context = "\n\n".join([result[0].page_content for result in results])
            metadata = results[0][0].metadata
            return context, metadata

        # Score too low — not confident enough
        return None, None

    except Exception as e:
        print(f"  ⚠️ Pinecone search error: {e}")
        return None, None


def search_who_live(query):
    
    try:
        # Search WHO website
        search_url = f"https://www.who.int/search?query={query}"
        response = requests.get(search_url, headers=SCRAPE_HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        # Find the first fact-sheet result link
        for link in soup.find_all("a", href=True):
            if "/news-room/fact-sheets/detail/" in link["href"]:
                page_url = "https://www.who.int" + str(link["href"])

                # Go to that fact sheet page and extract text
                page = requests.get(page_url, headers=SCRAPE_HEADERS, timeout=10)
                page_soup = BeautifulSoup(page.text, "html.parser")
                content = page_soup.find("div", {"class": "sf-detail-body-wrapper"})

                if content:
                    text = content.get_text(separator="\n", strip=True)

                    # Auto-save this new info to Pinecone for next time
                    save_new_data_to_pinecone(query, text, page_url)

                    return text[:2500], page_url  # limit to 2500 chars

        return None, None

    except Exception as e:
        print(f"  ⚠️ WHO live search error: {e}")
        return None, None


def save_new_data_to_pinecone(query, text, url):
    
    try:
        embeddings = get_embeddings()
        splitter = make_splitter()
        chunks = splitter.split_text(text)
        metadatas = [{"source": "WHO-live", "query": query, "url": url}] * len(chunks)

        vectorstore = get_vectorstore(embeddings)
        vectorstore.add_texts(texts=chunks, metadatas=metadatas)

        print(f"Saved {len(chunks)} new chunks to Pinecone")
    except Exception as e:
        print(f"Auto-save failed: {e}")


def format_answer(question, context, metadata,history=""):
    
    from src.prompt import RAG_WITH_HISTORY_PROMPT
    llm = get_llm()
    if history:
        prompt = RAG_WITH_HISTORY_PROMPT.format(
            system=SYSTEM_PROMPT,
            history=history,
            context=context,
            question=question
        )
    else:
        prompt = RAG_PROMPT_TEMPLATE.format(
            system=SYSTEM_PROMPT,
            context=context,
            question=question
        )
    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=prompt)
    ])
    return response.content


def ask_llm_fallback(question,history=""):
    
    llm = get_llm()
    history_section=""
    if history:
        history_section=f"\n\nPrevious conversation history:\n{history}\n\n"   
    prompt = FALLBACK_PROMPT_TEMPLATE.format(
        system=SYSTEM_PROMPT,
        question=question
    )+history_section
    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=prompt)
    ])
    return response.content


def ask_medical_question(query, vectorstore,chat_history=""):
    
    print(f"\nUser asked: {query}")

    
    context, metadata = search_pinecone(query, vectorstore)
    if context:
        print(" Found in Pinecone database (Layer 1)")
        answer = format_answer(query, context, metadata)
        metadata = metadata or {}
        return {
            "answer": answer,
            "source": metadata.get("source", "Medical Database"),
            "disease": metadata.get("disease", ""),
            "section": metadata.get("section", ""),
            "layer": 1,
            "layer_label": "Medical Database"
        }

    # ── Layer 2: Search WHO website live ───────────────────────
    print("  Not in database → searching WHO live (Layer 2)...")
    context, url = search_who_live(query)
    if context:
        print(f"Found on WHO website (Layer 2)")
        answer = format_answer(query, context, {"source": "WHO", "url": url})
        return {
            "answer": answer,
            "source": "WHO (live)",
            "url": url,
            "layer": 2,
            "layer_label": "WHO Live Search"
        }

    
    print(" Not on WHO → using AI knowledge (Layer 3)...")
    answer = ask_llm_fallback(query)
    return {
        "answer": answer,
        "source": "AI General Knowledge",
        "layer": 3,
        "layer_label": "AI Knowledge (consult a doctor)"
    }


def check_symptoms(symptoms_text, vectorstore):
    
    llm = get_llm()

    # Try to find relevant info from Pinecone based on symptoms
    context, metadata = search_pinecone(symptoms_text, vectorstore)

    # Build the prompt with symptoms + any relevant context found
    prompt = SYMPTOM_CHECKER_PROMPT.format(
        system=SYSTEM_PROMPT,
        symptoms=symptoms_text
    )
    if context:
        prompt += f"\n\nRelevant medical context from database:\n{context}"

    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=prompt)
    ])

    return {
        "answer": response.content,
        "source": "Symptom Analysis",
        "layer": 1 if context else 3,
        "layer_label": "Symptom Checker"
    }

