import os
import json
import logging
import pandas as pd
import pdfplumber
import google.generativeai as genai
from supabase import create_client, Client
from pydantic import BaseModel, Field
from typing import Optional, List

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load keys from environment variables (BEST PRACTICE)
try:
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    
    if not GOOGLE_API_KEY or not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("API keys and URL not found in environment variables.")
        
except ValueError as e:
    logging.error(f"{e} Please set GOOGLE_API_KEY, SUPABASE_URL, and SUPABASE_KEY.")
    exit(1)

INPUT_CSV = 'emails.csv'

# --- Pydantic Schema for Structured Output ---
# This tells Gemini *exactly* what JSON format we want.
class ProductInfo(BaseModel):
    product_name: Optional[str] = Field(description="The name of the product or item")
    price: Optional[float] = Field(description="The price of the product")
    sku: Optional[str] = Field(description="The Stock Keeping Unit or item number")

class SupplierData(BaseModel):
    supplier_name: Optional[str] = Field(description="The name of the supplier company")
    contact_email: Optional[str] = Field(description="A contact email for the supplier")
    products: List[ProductInfo] = Field(description="A list of products and their prices mentioned in the text")

def setup_clients():
    """Initializes and returns the Gemini model and Supabase client."""
    try:
        # Setup Gemini
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel(
            model_name='gemini-2.5-flash',
            generation_config={"response_mime_type": "application/json"}
        )
        logging.info("Google Gemini client initialized.")
        
        # Setup Supabase
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logging.info("Supabase client initialized.")
        
        return model, supabase
    except Exception as e:
        logging.error(f"Error initializing clients: {e}")
        return None, None

def parse_pdf_text(pdf_path: str) -> str:
    """Extracts all text from a single PDF file."""
    if not os.path.exists(pdf_path):
        logging.warning(f"PDF not found: {pdf_path}")
        return ""
        
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n\n"
        logging.info(f"Successfully parsed PDF: {pdf_path}")
    except Exception as e:
        logging.error(f"Failed to parse PDF {pdf_path}: {e}")
    return text

def extract_with_gemini(text_to_parse: str, model) -> Optional[dict]:
    """
    Sends text to Gemini API and asks for structured JSON output
    based on our Pydantic schema.
    """
    if not text_to_parse.strip():
        logging.warning("No text to parse, skipping Gemini.")
        return None

    prompt = f"""
    You are an expert data extraction assistant.
    Analyze the following text, which is from a supplier email or a PDF attachment (like a price list or quotation).
    Extract the supplier's name, any contact email, and a list of all products or services mentioned with their prices and SKUs.
    
    Respond *only* with a valid JSON object matching the requested schema.
    If a value is not found, omit it or set it to null.
    
    TEXT TO ANALYZE:
    ---
    {text_to_parse}
    ---
    """
    
    response = None  # <-- THIS IS THE FIX FOR THE UnboundLocalError
    try:
        response = model.generate_content(
            [prompt],
            generation_config=genai.types.GenerationConfig(
                response_schema=SupplierData, # This is the magic!
            )
        )
        
        # The API automatically parses the JSON for us when using response_schema
        data = json.loads(response.text)
        logging.info("Successfully extracted structured data from text.")
        return data
        
    except Exception as e:
        logging.error(f"Error calling Gemini API or parsing JSON: {e}")
        # Now this logging line is safe
        if response:
            logging.error(f"Gemini raw response (if any): {response.text}")
        else:
            logging.error("Gemini request failed before a response was received.")
        return None

def main():
    """Main processing loop for Day 2."""
    logging.info("--- Starting Day 2: Parse, Extract, Store (v3 - Per-Document) ---")
    
    model, supabase = setup_clients()
    if not model or not supabase:
        logging.error("Failed to initialize clients. Exiting.")
        return

    try:
        df = pd.read_csv(INPUT_CSV).fillna('')
    except FileNotFoundError:
        logging.error(f"Input file not found: {INPUT_CSV}. Run Day 1 first.")
        return

    logging.info(f"Loaded {len(df)} emails from {INPUT_CSV}")

    for index, row in df.iterrows():
        email_id = row['id']
        logging.info(f"--- Processing email ID: {email_id} ---")

        # --- Create a list of all 'documents' (body + attachments) to process ---
        documents_to_process = []

        # 1. Add the email body
        documents_to_process.append({
            "source_name": f"body_{email_id}", # A unique name for this "document"
            "text": row['body'],
            "csv_attachment_list": row['attachment_paths'] # Keep the original list
        })
        
        # 2. Add each PDF attachment
        pdf_paths_str = row.get('attachment_paths', '')
        if pdf_paths_str:
            pdf_paths = [p.strip() for p in pdf_paths_str.split(';') if p.strip()]
            for pdf_path in pdf_paths:
                documents_to_process.append({
                    "source_name": pdf_path, # The file path is the unique name
                    "text": parse_pdf_text(pdf_path),
                    "csv_attachment_list": row['attachment_paths']
                })
        
        # --- Now, loop through each document and process it individually ---
        for doc in documents_to_process:
            doc_source_name = doc['source_name']
            doc_text = doc['text'].replace('\u0000', '') # Sanitize text
            
            if not doc_text:
                logging.info(f"No text found in {doc_source_name}. Skipping.")
                continue

            logging.info(f"Processing document: {doc_source_name}")

            # --- FIX 1: CHECK DUPLICATES PER-DOCUMENT ---
            try:
                # Check if this *specific document* has been processed
                response = supabase.table('supplier_info').select('id').eq('source_pdf_path', doc_source_name).execute()
                
                if response.data:
                    logging.info(f"Document {doc_source_name} already processed. Skipping.")
                    continue
            except Exception as e:
                logging.error(f"Error checking for existing doc {doc_source_name}: {e}")
                continue

            # --- END FIX 1 ---

            # 3. Extract structured data from this *single* document
            extracted_data = extract_with_gemini(doc_text, model)
            
            if not extracted_data:
                logging.warning(f"No data extracted from {doc_source_name}. Skipping.")
                continue

            # --- FIX 2: LOOP THROUGH PRODUCTS (same as before) ---
            supplier_name = extracted_data.get('supplier_name')
            products_list = extracted_data.get('products', [])
            
            if not products_list:
                logging.warning(f"No products found in {doc_source_name}. Skipping.")
                continue

            logging.info(f"Found {len(products_list)} products in {doc_source_name}.")
            
            rows_to_insert = []
            for product in products_list:
                insert_row = {
                    "supplier_name": supplier_name,
                    "product_name": product.get('product_name'),
                    "price": product.get('price'),
                    "extracted_data": extracted_data,
                    "source_email_id": email_id,
                    # This is the key change: store the *specific file*
                    "source_pdf_path": doc_source_name, 
                    "raw_text": doc_text
                }
                rows_to_insert.append(insert_row)
            
            # 4. Insert all rows for this *document* in a batch
            if rows_to_insert:
                try:
                    # This is the fix.
                    # We use upsert and tell it to do nothing on conflict.
                    response = supabase.table('supplier_info').upsert(
                        rows_to_insert, 
                        on_conflict='source_pdf_path,product_name' # This is the constraint name
                    ).execute()
                    
                    if response.error:
                        logging.error(f"Supabase upsert error for {doc_source_name}: {response.error}")
                    else:
                        logging.info(f"Successfully upserted/skipped {len(rows_to_insert)} products from {doc_source_name}")
                except Exception as e:
                    logging.error(f"Error during Supabase batch upsert: {e}")

    logging.info("--- Day 2 Complete ---")

if __name__ == '__main__':
    main()