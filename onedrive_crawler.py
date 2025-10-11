import os
import msal
import requests
import io
import json
from pathlib import Path
from dotenv import load_dotenv
import fitz  # PyMuPDF
from docx import Document
from pptx import Presentation
from openpyxl import load_workbook
import olefile
from PIL import Image
import warnings
import csv
import zipfile

# Suppress PyTorch warnings about GPU/accelerator
warnings.filterwarnings('ignore', category=UserWarning, module='torch')

import easyocr
from pinecone import Pinecone
from embeddings import EmbeddingProvider
from config import settings

load_dotenv()

CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
TENANT_ID = os.getenv("MICROSOFT_TENANT_ID")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["Files.Read.All", "User.Read"]

# Token cache file
TOKEN_CACHE_FILE = Path.home() / ".smartdrive_token_cache.json"

# Folder skip cache file (remembers your choices)
FOLDER_SKIP_CACHE_FILE = Path.home() / ".smartdrive_folder_skip_cache.json"

# Global settings for this run
EXTRACT_ZIP_CONTENTS = False  # Will be set based on user choice

# Initialize Pinecone
pc = Pinecone(api_key=settings.PINECONE_API_KEY)
index = pc.Index(
    name=settings.PINECONE_INDEX_NAME,
    host=settings.PINECONE_HOST
)

# Initialize embedding provider
print(f"🧠 Loading {settings.EMBEDDING_PROVIDER} embedding provider ({settings.EMBEDDING_MODEL})...")
embedding_provider = EmbeddingProvider()
print("✅ Embedding provider loaded\n")

# Initialize EasyOCR reader (lazy-loaded on first use)
ocr_reader = None

def get_ocr_reader():
    """Lazy-load EasyOCR reader (downloads models on first use)"""
    global ocr_reader
    if ocr_reader is None:
        print("🔍 Loading OCR model (first time only, may take a moment)...")
        ocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        print("✅ OCR model loaded\n")
    return ocr_reader

def load_token_cache():
    """Load token cache from file"""
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_FILE.exists():
        with open(TOKEN_CACHE_FILE, 'r') as f:
            cache.deserialize(f.read())
    return cache

def save_token_cache(cache):
    """Save token cache to file"""
    if cache.has_state_changed:
        with open(TOKEN_CACHE_FILE, 'w') as f:
            f.write(cache.serialize())

def get_access_token(silent_only=False):
    """Authenticate using device code flow with token caching

    Args:
        silent_only: If True, only attempt silent token refresh (no interactive prompts)
    """
    cache = load_token_cache()
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    # Try to get token silently from cache first
    accounts = app.get_accounts()
    if accounts:
        if not silent_only:
            print("🔄 Using cached credentials...")
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            save_token_cache(cache)
            if not silent_only:
                print("✅ Authentication successful (cached)\n")
            return result["access_token"]

    # If silent_only mode, return None (caller will handle)
    if silent_only:
        return None

    # If silent auth fails, do interactive device flow
    print("🔐 No cached credentials found, starting authentication...")
    flow = app.initiate_device_flow(scopes=SCOPES)

    if "user_code" not in flow:
        raise Exception(f"Failed to create device flow: {flow.get('error_description', 'Unknown error')}")

    print(f"\n🔐 Go to: {flow['verification_uri']}")
    print(f"📱 Enter code: {flow['user_code']}\n")

    result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        save_token_cache(cache)
        return result["access_token"]
    else:
        raise Exception(f"Authentication failed: {result.get('error_description')}")

def extract_text_from_zip_item(file_name, content):
    """Extract text from files inside zip archives"""
    file_name_lower = file_name.lower()

    try:
        # PDF
        if file_name_lower.endswith('.pdf'):
            pdf = fitz.open(stream=content, filetype="pdf")
            text = ""
            for page_num in range(min(pdf.page_count, 10)):  # Limit to 10 pages per PDF in zip
                text += pdf[page_num].get_text() + "\n"
            pdf.close()
            return text.strip()

        # Word (.docx)
        elif file_name_lower.endswith('.docx'):
            doc = Document(io.BytesIO(content))
            text = "\n".join([para.text for para in doc.paragraphs])
            return text.strip()

        # PowerPoint (.pptx)
        elif file_name_lower.endswith('.pptx'):
            prs = Presentation(io.BytesIO(content))
            text_parts = []
            for slide_num, slide in enumerate(prs.slides, 1):
                text_parts.append(f"Slide {slide_num}:")
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text:
                        text_parts.append(shape.text)
            return "\n".join(text_parts).strip()

        # Markdown
        elif file_name_lower.endswith(('.md', '.markdown')):
            return content.decode('utf-8', errors='ignore').strip()

        # Plain text
        elif file_name_lower.endswith('.txt'):
            return content.decode('utf-8', errors='ignore').strip()

        # CSV
        elif file_name_lower.endswith('.csv'):
            text_content = content.decode('utf-8', errors='ignore')
            csv_reader = csv.reader(io.StringIO(text_content))
            rows = list(csv_reader)[:50]  # Limit rows
            text_parts = []
            for row in rows:
                row_text = " | ".join([str(cell) for cell in row if cell])
                if row_text.strip():
                    text_parts.append(row_text)
            return "\n".join(text_parts).strip()

        # JSON
        elif file_name_lower.endswith('.json'):
            try:
                text_content = content.decode('utf-8', errors='ignore')
                json_data = json.loads(text_content)
                formatted_json = json.dumps(json_data, indent=2, ensure_ascii=False)
                return formatted_json[:5000]  # Limit JSON size
            except:
                return content.decode('utf-8', errors='ignore').strip()[:5000]

        # Excel
        elif file_name_lower.endswith(('.xlsx', '.xlsm')):
            workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
            text_parts = []
            for sheet_name in workbook.sheetnames[:3]:  # Limit to 3 sheets
                sheet = workbook[sheet_name]
                text_parts.append(f"Sheet: {sheet_name}")
                for idx, row in enumerate(sheet.iter_rows(values_only=True)):
                    if idx > 50:  # Limit rows per sheet
                        break
                    row_text = " | ".join([str(cell) if cell is not None else "" for cell in row])
                    if row_text.strip():
                        text_parts.append(row_text)
            workbook.close()
            return "\n".join(text_parts).strip()

        else:
            return None

    except Exception as e:
        return None

def extract_text_from_file(token, file_item):
    """Download and extract text from supported file types"""
    headers = {"Authorization": f"Bearer {token}"}
    download_url = file_item.get("@microsoft.graph.downloadUrl")
    
    if not download_url:
        return None
    
    # Download file content
    response = requests.get(download_url)
    if response.status_code != 200:
        return None
    
    file_name = file_item["name"].lower()
    content = response.content
    
    try:
        # PDF extraction (with OCR fallback for scanned docs)
        if file_name.endswith('.pdf'):
            pdf = fitz.open(stream=content, filetype="pdf")
            text = ""

            # Try normal text extraction first
            for page_num in range(pdf.page_count):
                page = pdf[page_num]
                page_text = page.get_text()
                if page_text:
                    text += page_text + "\n"

            # If no text found or very little text (likely scanned), use OCR
            if len(text.strip()) < 50:
                print(f"   🔍 Scanned PDF detected ({pdf.page_count} pages), using OCR...")
                print(f"      ⏳ This may take 3-10 seconds per page...")
                try:
                    reader = get_ocr_reader()
                    ocr_text = ""
                    for page_num in range(pdf.page_count):
                        print(f"      📄 Page {page_num+1}/{pdf.page_count}...", end=" ", flush=True)
                        page = pdf[page_num]
                        # Render page to image (pixmap) at 300 DPI
                        pix = page.get_pixmap(dpi=300)
                        # Convert pixmap to numpy array for EasyOCR
                        import numpy as np
                        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                        # Run OCR on the image
                        result = reader.readtext(img_array, detail=0, paragraph=True)
                        page_text = "\n".join(result)
                        ocr_text += f"=== Page {page_num+1} ===\n{page_text}\n"
                        print("✓")
                    print(f"      ✅ OCR complete!")
                    text = ocr_text
                except Exception as ocr_error:
                    print(f"   ⚠️ OCR failed: {ocr_error}")
                    # Return whatever text we got from normal extraction
                    pass

            pdf.close()
            return text.strip()

        # Word doc extraction (.docx)
        elif file_name.endswith('.docx'):
            doc = Document(io.BytesIO(content))
            text = "\n".join([para.text for para in doc.paragraphs])
            return text.strip()

        # Legacy Word doc extraction (.doc)
        elif file_name.endswith('.doc'):
            try:
                ole = olefile.OleFileIO(content)
                if ole.exists('WordDocument'):
                    # Try to extract text from Word 97-2003 format
                    # This is a simplified extraction - won't get all formatting
                    word_stream = ole.openstream('WordDocument')
                    data = word_stream.read()
                    # Simple heuristic: extract printable ASCII/Unicode text
                    text = data.decode('latin-1', errors='ignore')
                    # Clean up - remove non-printable chars but keep newlines/spaces
                    text = ''.join(c for c in text if c.isprintable() or c in '\n\r\t ')
                    # Remove excessive whitespace
                    text = '\n'.join(line.strip() for line in text.split('\n') if line.strip())
                    ole.close()
                    return text.strip() if len(text.strip()) > 20 else None
                else:
                    print(f"   ⚠️ Not a valid .doc file")
                    ole.close()
                    return None
            except Exception as e:
                print(f"   ⚠️ Failed to parse .doc file: {e}")
                return None

        # PowerPoint extraction (.pptx, .ppt)
        elif file_name.endswith(('.pptx', '.ppt')):
            try:
                prs = Presentation(io.BytesIO(content))
                text_parts = []
                for slide_num, slide in enumerate(prs.slides, 1):
                    text_parts.append(f"=== Slide {slide_num} ===")
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text:
                            text_parts.append(shape.text)
                return "\n".join(text_parts).strip()
            except Exception as pptx_error:
                print(f"   ⚠️ PowerPoint parsing failed: {pptx_error}")
                return None

        # Markdown extraction (.md)
        elif file_name.endswith(('.md', '.markdown')):
            try:
                # Markdown is already plain text, just decode it
                text = content.decode('utf-8', errors='ignore')
                return text.strip()
            except Exception as md_error:
                print(f"   ⚠️ Markdown parsing failed: {md_error}")
                return None

        # Excel extraction
        elif file_name.endswith(('.xlsx', '.xlsm', '.xltx', '.xltm')):
            try:
                workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
                text_parts = []
                for sheet_name in workbook.sheetnames:
                    sheet = workbook[sheet_name]
                    text_parts.append(f"=== Sheet: {sheet_name} ===")
                    for row in sheet.iter_rows(values_only=True):
                        row_text = " | ".join([str(cell) if cell is not None else "" for cell in row])
                        if row_text.strip():
                            text_parts.append(row_text)
                workbook.close()
                return "\n".join(text_parts).strip()
            except Exception as excel_error:
                print(f"   ⚠️ Excel parsing failed: {excel_error}")
                return None

        # Image extraction with OCR
        elif file_name.endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif', '.img')):
            import numpy as np
            reader = get_ocr_reader()
            image = Image.open(io.BytesIO(content))
            # Convert PIL image to numpy array
            img_array = np.array(image)
            # Run OCR
            result = reader.readtext(img_array, detail=0, paragraph=True)
            text = "\n".join(result)
            return text.strip() if text.strip() else None

        # Plain text
        elif file_name.endswith('.txt'):
            return content.decode('utf-8', errors='ignore').strip()

        # CSV extraction
        elif file_name.endswith('.csv'):
            try:
                # Try UTF-8 first, fallback to latin-1
                try:
                    text_content = content.decode('utf-8')
                except UnicodeDecodeError:
                    text_content = content.decode('latin-1', errors='ignore')

                # Parse CSV
                csv_reader = csv.reader(io.StringIO(text_content))
                rows = list(csv_reader)

                # Format as readable text
                text_parts = []
                for row in rows:
                    row_text = " | ".join([str(cell) for cell in row if cell])
                    if row_text.strip():
                        text_parts.append(row_text)

                return "\n".join(text_parts).strip()
            except Exception as csv_error:
                print(f"   ⚠️ CSV parsing failed: {csv_error}")
                return None

        # JSON extraction
        elif file_name.endswith('.json'):
            try:
                text_content = content.decode('utf-8', errors='ignore')
                json_data = json.loads(text_content)

                # Pretty print JSON for readability
                formatted_json = json.dumps(json_data, indent=2, ensure_ascii=False)
                return formatted_json
            except Exception as json_error:
                print(f"   ⚠️ JSON parsing failed: {json_error}")
                # Fall back to raw text if JSON parsing fails
                try:
                    return content.decode('utf-8', errors='ignore').strip()
                except:
                    return None

        # ZIP file handling
        elif file_name.endswith('.zip'):
            try:
                zip_file = zipfile.ZipFile(io.BytesIO(content))
                file_list = zip_file.namelist()

                if EXTRACT_ZIP_CONTENTS:
                    # Option 2: Extract and index contents
                    print(f"   📦 Extracting {len(file_list)} files from archive...")
                    extracted_texts = []
                    extracted_texts.append(f"=== Archive: {file_name} ===")
                    extracted_texts.append(f"Contains {len(file_list)} files\n")

                    for zip_item_name in file_list[:50]:  # Limit to 50 files per archive
                        try:
                            # Skip directories
                            if zip_item_name.endswith('/'):
                                continue

                            zip_item_ext = zip_item_name.lower().split('.')[-1] if '.' in zip_item_name else ''
                            supported_in_zip = ['pdf', 'docx', 'doc', 'pptx', 'txt', 'csv', 'json', 'md', 'markdown', 'xlsx']

                            if zip_item_ext in supported_in_zip:
                                print(f"      📄 Extracting: {zip_item_name}")
                                zip_item_content = zip_file.read(zip_item_name)

                                # Create a fake file_item for extract_text_from_file
                                fake_item = {
                                    'name': zip_item_name,
                                    '@microsoft.graph.downloadUrl': None  # Signal we have content already
                                }

                                # Use a custom extraction for zip contents
                                zip_text = extract_text_from_zip_item(zip_item_name, zip_item_content)
                                if zip_text:
                                    extracted_texts.append(f"\n=== File: {zip_item_name} ===")
                                    extracted_texts.append(zip_text[:2000])  # Limit each file to 2000 chars
                        except Exception as zip_item_error:
                            print(f"      ⚠️ Failed to extract {zip_item_name}: {zip_item_error}")
                            continue

                    zip_file.close()
                    return "\n".join(extracted_texts).strip()
                else:
                    # Option 3: Just list contents (default)
                    text_parts = []
                    text_parts.append(f"=== Archive: {file_name} ===")
                    text_parts.append(f"Contains {len(file_list)} files:")
                    for item in file_list[:100]:  # List up to 100 files
                        text_parts.append(f"  • {item}")
                    if len(file_list) > 100:
                        text_parts.append(f"  ... and {len(file_list) - 100} more files")

                    zip_file.close()
                    return "\n".join(text_parts).strip()

            except Exception as zip_error:
                print(f"   ⚠️ ZIP processing failed: {zip_error}")
                return None

        else:
            return None

    except Exception as e:
        print(f"❌ Failed to extract {file_name}: {e}")
        return None

def upload_to_pinecone(files_data):
    """Upload extracted files to Pinecone with embeddings"""
    print(f"\n📤 Uploading {len(files_data)} files to Pinecone...")

    vectors = []
    for idx, file_data in enumerate(files_data):
        # Generate embedding
        text = file_data["text"][:8000]  # Truncate to reasonable length
        embedding = embedding_provider.get_embedding_sync(text)

        if embedding is None:
            print(f"   ⚠️ Failed to generate embedding for: {file_data['name']}")
            continue

        embedding = embedding.tolist()
        
        vector_id = f"doc_{idx}_{file_data['name']}"
        
        vectors.append({
            "id": vector_id,
            "values": embedding,
            "metadata": {
                "file_name": file_data["name"],
                "file_path": file_data["path"],
                "size": file_data["size"],
                "modified": file_data["modified"],
                "text_preview": text[:500]  # Store preview for display
            }
        })
        print(f"   🔢 Embedded: {file_data['name']}")
    
    # Upsert to Pinecone
    index.upsert(vectors=vectors, namespace="smartdrive")
    print(f"✅ Uploaded {len(vectors)} documents to Pinecone")

def load_folder_skip_cache():
    """Load folder skip preferences from cache"""
    if FOLDER_SKIP_CACHE_FILE.exists():
        with open(FOLDER_SKIP_CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_folder_skip_cache(cache):
    """Save folder skip preferences to cache"""
    with open(FOLDER_SKIP_CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def should_process_folder(folder_path, folder_name, skip_cache, interactive=True):
    """Ask user if they want to process this folder
    Returns: 'process', 'skip', or 'list-only'
    """
    cache_key = folder_path

    # Check cache first
    if cache_key in skip_cache:
        decision = skip_cache[cache_key]
        if decision == "skip":
            print(f"📁 {folder_name}/ [SKIPPED - cached choice]")
            return "skip"
        elif decision == "process":
            print(f"📁 {folder_name}/ [PROCESSING - cached choice]")
            return "process"
        elif decision == "list-only":
            print(f"📁 {folder_name}/ [LIST ONLY - cached choice]")
            return "list-only"

    # Ask user if interactive
    if interactive:
        print(f"\n📁 Found folder: {folder_name}/")
        print(f"   Path: {folder_path}")
        while True:
            choice = input("   [y]es / [n]o / [l]ist-only / [a]lways yes / [s]kip always / [o]nly list always: ").lower().strip()
            if choice in ['y', 'yes', '']:
                return "process"
            elif choice in ['n', 'no']:
                return "skip"
            elif choice in ['l', 'list', 'list-only']:
                return "list-only"
            elif choice in ['a', 'always']:
                skip_cache[cache_key] = "process"
                save_folder_skip_cache(skip_cache)
                print(f"   ✅ Will always process this folder")
                return "process"
            elif choice in ['s', 'skip']:
                skip_cache[cache_key] = "skip"
                save_folder_skip_cache(skip_cache)
                print(f"   ⏭️ Will always skip this folder")
                return "skip"
            elif choice in ['o', 'only', 'only-list']:
                skip_cache[cache_key] = "list-only"
                save_folder_skip_cache(skip_cache)
                print(f"   📋 Will always list-only this folder")
                return "list-only"
            else:
                print("   Invalid choice, please try again.")

    # Default: process if not interactive
    return "process"

def list_folder_contents_only(token, folder_id, folder_path, extracted_files, processed_count):
    """Recursively list all files in a folder without extracting content (like ZIP list mode)"""
    headers = {"Authorization": f"Bearer {token}"}
    base_url = "https://graph.microsoft.com/v1.0/me/drive"

    # List items in current folder
    url = f"{base_url}/items/{folder_id}/children"
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"   ⚠️ Failed to access folder: {response.text}")
        return

    items = response.json().get("value", [])
    folders = [item for item in items if "folder" in item]
    files = [item for item in items if "file" in item]

    # Collect file listing
    file_list = []
    for item in files:
        file_name = item['name']
        file_size = item.get("size", 0)
        file_modified = item.get("lastModifiedDateTime", "")
        file_list.append(f"  • {file_name} ({file_size} bytes)")
        processed_count[0] += 1

    # Recursively list subfolders
    for folder_item in folders:
        folder_name = folder_item['name']
        subfolder_path = f"{folder_path}/{folder_name}"
        subfolder_id = folder_item['id']

        # Get subfolder contents
        subfolder_url = f"{base_url}/items/{subfolder_id}/children"
        subfolder_response = requests.get(subfolder_url, headers=headers)
        if subfolder_response.status_code == 200:
            subfolder_items = subfolder_response.json().get("value", [])
            subfolder_files = [item for item in subfolder_items if "file" in item]
            for item in subfolder_files:
                file_name = item['name']
                file_size = item.get("size", 0)
                file_list.append(f"  • {subfolder_path}/{file_name} ({file_size} bytes)")
                processed_count[0] += 1

            # Recurse deeper
            subfolder_folders = [item for item in subfolder_items if "folder" in item]
            for sub_folder_item in subfolder_folders:
                list_folder_contents_only(
                    token, sub_folder_item['id'], f"{subfolder_path}/{sub_folder_item['name']}",
                    extracted_files, processed_count
                )

    # Create a single entry with the folder listing
    if file_list:
        folder_listing_text = f"=== Folder: {folder_path} ===\n"
        folder_listing_text += f"Contains {len(file_list)} files:\n"
        folder_listing_text += "\n".join(file_list)

        extracted_files.append({
            "name": f"{folder_path.split('/')[-1]} (folder listing)",
            "path": folder_path,
            "text": folder_listing_text,
            "size": 0,
            "modified": ""
        })
        print(f"   ✅ Listed {len(file_list)} files")

def is_token_expired(response):
    """Check if response indicates token expiration"""
    if response.status_code == 401:
        return True
    if response.status_code == 400:
        try:
            error_data = response.json()
            error_msg = str(error_data.get("error", {})).lower()
            return "invalidauthenticationtoken" in error_msg or "jwt" in error_msg or "token" in error_msg
        except:
            pass
    return False

def crawl_folder_recursive(token_ref, folder_id, folder_path, max_files, skip_cache, extracted_files, failed_files, skipped_files, processed_count, interactive=True):
    """Recursively crawl folders and extract files

    Args:
        token_ref: List containing the current access token [token]. Using a list allows updating the token reference.
    """
    headers = {"Authorization": f"Bearer {token_ref[0]}"}
    base_url = "https://graph.microsoft.com/v1.0/me/drive"

    # List items in current folder
    url = f"{base_url}/items/{folder_id}/children"
    response = requests.get(url, headers=headers)

    # If token expired, try to refresh it
    if is_token_expired(response):
        print(f"   🔄 Token expired, refreshing...")
        new_token = get_access_token(silent_only=True)
        if new_token:
            token_ref[0] = new_token  # Update token reference
            headers = {"Authorization": f"Bearer {token_ref[0]}"}
            response = requests.get(url, headers=headers)  # Retry request
            print(f"   ✅ Token refreshed successfully")
        else:
            print(f"   ❌ Token refresh failed")
            return processed_count[0]

    if response.status_code != 200:
        print(f"   ⚠️ Failed to access folder: {response.text}")
        return processed_count[0]

    items = response.json().get("value", [])

    # Process folders first (for interactive selection)
    folders = [item for item in items if "folder" in item]
    files = [item for item in items if "file" in item]

    # Process subfolders
    for folder_item in folders:
        if processed_count[0] >= max_files:
            break

        folder_name = folder_item['name']
        subfolder_path = f"{folder_path}/{folder_name}"
        subfolder_id = folder_item['id']

        # Ask if we should process this folder
        folder_mode = should_process_folder(subfolder_path, folder_name, skip_cache, interactive)

        if folder_mode == "process":
            # Full processing - recurse into subfolder
            crawl_folder_recursive(
                token_ref, subfolder_id, subfolder_path, max_files, skip_cache,
                extracted_files, failed_files, skipped_files, processed_count, interactive
            )
        elif folder_mode == "list-only":
            # List-only mode - just index filenames and paths (like ZIP list mode)
            print(f"   📋 Listing files only (not extracting content)")
            list_folder_contents_only(
                token_ref[0], subfolder_id, subfolder_path, extracted_files, processed_count
            )
        # else: skip - do nothing

    # Process files in current folder
    for item in files:
        if processed_count[0] >= max_files:
            print(f"\n⚠️ Reached {max_files} file limit")
            break

        file_name = item['name']
        file_ext = file_name.lower().split('.')[-1] if '.' in file_name else 'no extension'
        print(f"📄 Processing: {folder_path}/{file_name}")

        text = extract_text_from_file(token_ref[0], item)

        if text:
            print(f"   ✅ Extracted {len(text)} characters")
            extracted_files.append({
                "name": file_name,
                "path": f"{folder_path}/{file_name}",
                "text": text,
                "size": item.get("size", 0),
                "modified": item.get("lastModifiedDateTime", "")
            })
        elif text is None:
            supported_extensions = ['pdf', 'docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xlsm', 'xltx', 'xltm',
                                   'png', 'jpg', 'jpeg', 'tiff', 'bmp', 'gif', 'img', 'txt', 'csv', 'json', 'md', 'markdown', 'zip']
            if file_ext in supported_extensions:
                failed_files.append((file_name, file_ext))
                print(f"   ❌ Failed to extract (see error above)")
            else:
                skipped_files.append((file_name, file_ext))
                print(f"   ⚠️ Skipped (unsupported type: .{file_ext})")

        processed_count[0] += 1

    return processed_count[0]

def discover_all_folders(token, folder_id, folder_path="/Documents", folders_list=None, depth=0):
    """Recursively discover all folders in the tree without processing files

    Returns: List of tuples [(folder_path, folder_name, folder_id), ...]
    """
    if folders_list is None:
        folders_list = []

    headers = {"Authorization": f"Bearer {token}"}
    base_url = "https://graph.microsoft.com/v1.0/me/drive"

    # List items in current folder
    url = f"{base_url}/items/{folder_id}/children"

    try:
        response = requests.get(url, headers=headers, timeout=10)  # 10 second timeout
    except requests.exceptions.Timeout:
        print(f"   ⏱️ Timeout on {folder_path} (>10s), retrying with 30s timeout...")
        try:
            response = requests.get(url, headers=headers, timeout=30)  # Retry with longer timeout
        except:
            print(f"   ❌ Still timeout. This folder's subfolders won't be discovered.")
            # Note: The folder itself is already in the list, just can't get its subfolders
            return folders_list
    except requests.exceptions.RequestException as e:
        print(f"   ⚠️ Network error on {folder_path}: {str(e)[:80]}")
        print(f"   ⚠️ This folder's subfolders won't be discovered, but you can still choose it.")
        return folders_list

    if response.status_code != 200:
        print(f"   ⚠️ API error {response.status_code} on {folder_path}")
        return folders_list

    items = response.json().get("value", [])

    # Find all subfolders
    subfolder_items = [item for item in items if "folder" in item]

    for item in subfolder_items:
        folder_name = item['name']
        subfolder_path = f"{folder_path}/{folder_name}"
        subfolder_id = item['id']

        # Add this folder to the list
        folders_list.append((subfolder_path, folder_name, subfolder_id))

        # Show progress more frequently (every 5 folders)
        if len(folders_list) % 5 == 0:
            print(f"   ... {len(folders_list)} folders discovered")

        # Recursively discover subfolders
        discover_all_folders(token, subfolder_id, subfolder_path, folders_list, depth + 1)

    return folders_list

def interactive_folder_selection(folders_list, skip_cache):
    """Present all folders to user and let them choose how to handle each one

    Returns: Updated skip_cache with user preferences
    """
    print("\n" + "=" * 60)
    print("📁 FOLDER SELECTION - Choose how to handle each folder")
    print("=" * 60)
    print(f"Found {len(folders_list)} folders in your Documents directory.")
    print("\nFor each folder, choose:")
    print("  [y] = Process (extract all file contents)")
    print("  [l] = List-only (index filenames without extracting)")
    print("  [n] = Skip (ignore this folder)")
    print("  [q] = Quick mode - assume 'yes' for all remaining folders")
    print("=" * 60)

    quick_mode = False

    for idx, (folder_path, folder_name, folder_id) in enumerate(folders_list, 1):
        # Check if we already have a cached decision
        if folder_path in skip_cache:
            decision = skip_cache[folder_path]
            status = {"process": "✅ PROCESS", "list-only": "📋 LIST-ONLY", "skip": "⏭️  SKIP"}[decision]
            print(f"\n[{idx}/{len(folders_list)}] {folder_name}/")
            print(f"   Path: {folder_path}")
            print(f"   {status} (cached)")
            continue

        # In quick mode, default to process
        if quick_mode:
            skip_cache[folder_path] = "process"
            print(f"\n[{idx}/{len(folders_list)}] {folder_name}/ → ✅ PROCESS (quick mode)")
            continue

        # Ask user
        print(f"\n[{idx}/{len(folders_list)}] {folder_name}/")
        print(f"   Path: {folder_path}")

        while True:
            choice = input("   Choice [y/l/n/q]: ").lower().strip()

            if choice in ['y', 'yes', '']:
                skip_cache[folder_path] = "process"
                print("   → ✅ Will PROCESS this folder")
                break
            elif choice in ['l', 'list', 'list-only']:
                skip_cache[folder_path] = "list-only"
                print("   → 📋 Will LIST-ONLY this folder")
                break
            elif choice in ['n', 'no', 'skip']:
                skip_cache[folder_path] = "skip"
                print("   → ⏭️  Will SKIP this folder")
                break
            elif choice in ['q', 'quick']:
                skip_cache[folder_path] = "process"
                quick_mode = True
                print("   → ✅ Will PROCESS this folder")
                print("   🚀 Quick mode enabled - all remaining folders will be processed")
                break
            else:
                print("   Invalid choice, please enter y/l/n/q")

    # Save updated cache
    save_folder_skip_cache(skip_cache)

    print("\n" + "=" * 60)
    print("✅ Folder selection complete!")

    # Show summary
    process_count = sum(1 for v in skip_cache.values() if v == "process")
    list_count = sum(1 for v in skip_cache.values() if v == "list-only")
    skip_count = sum(1 for v in skip_cache.values() if v == "skip")

    print(f"   ✅ Process: {process_count} folders")
    print(f"   📋 List-only: {list_count} folders")
    print(f"   ⏭️  Skip: {skip_count} folders")
    print("=" * 60)

    return skip_cache

def list_documents_folder(token, max_files=None, interactive=True, preflight=True):
    """Recursively crawl Documents folder with interactive folder selection

    Args:
        preflight: If True, discover all folders first and let user choose before crawling
    """
    headers = {"Authorization": f"Bearer {token}"}
    base_url = "https://graph.microsoft.com/v1.0/me/drive"

    # Get Documents folder
    url = f"{base_url}/root:/Documents"
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Failed to access Documents folder: {response.text}")

    folder_id = response.json()["id"]

    # Load folder skip cache
    skip_cache = load_folder_skip_cache()

    # PREFLIGHT MODE: Discover all folders first, let user choose
    if preflight and interactive:
        print(f"🔍 Discovering all folders in Documents directory...")
        folders_list = discover_all_folders(token, folder_id, "/Documents")
        print(f"✅ Found {len(folders_list)} folders\n")

        # Let user select how to handle each folder
        skip_cache = interactive_folder_selection(folders_list, skip_cache)

        print("\n🚀 Starting crawl with your folder preferences...\n")
        # Now interactive is False for the actual crawl (decisions already made)
        interactive = False

    # Initialize tracking
    extracted_files = []
    failed_files = []
    skipped_files = []
    processed_count = [0]  # Use list to allow modification in recursive calls

    # Set max_files to a very large number if None
    if max_files is None:
        max_files = 999999

    print(f"🔍 Crawling Documents folder recursively...")
    if interactive:
        print(f"💡 Tip: You'll be asked about each folder. Choose 'always' to remember your choice!\n")

    # Start recursive crawl (pass token as reference list for refresh capability)
    token_ref = [token]
    crawl_folder_recursive(
        token_ref, folder_id, "/Documents", max_files, skip_cache,
        extracted_files, failed_files, skipped_files, processed_count, interactive
    )

    # Print summary
    print(f"\n{'='*60}")
    print(f"📊 Processing Summary:")
    print(f"{'='*60}")
    print(f"✅ Successfully extracted: {len(extracted_files)} files")

    if failed_files:
        print(f"\n❌ Failed extractions ({len(failed_files)}):")
        for fname, ext in failed_files:
            print(f"   • {fname} (.{ext})")

    if skipped_files:
        print(f"\n⚠️ Unsupported file types ({len(skipped_files)}):")
        type_counts = {}
        for fname, ext in skipped_files:
            type_counts[ext] = type_counts.get(ext, 0) + 1
        for ext, count in type_counts.items():
            print(f"   • .{ext}: {count} file(s)")

    print(f"{'='*60}\n")

    return extracted_files

if __name__ == "__main__":
    import asyncio

    token = get_access_token()
    print("✅ Authentication successful!\n")

    # Check if folder cache exists
    skip_cache = load_folder_skip_cache()
    has_cache = len(skip_cache) > 0

    # Main menu
    while True:
        print("=" * 60)
        print("📋 SmartDrive Crawler - Main Menu")
        print("=" * 60)
        print("1. Run crawler (use cached folder choices)")
        print("2. Reset folder choices and start fresh")
        print("3. View/edit cached folder choices")
        print("4. Exit")
        print("=" * 60)

        if has_cache:
            print(f"ℹ️  You have {len(skip_cache)} cached folder choice(s)")
        else:
            print("ℹ️  No cached folder choices yet")

        choice = input("\nSelect option [1-4]: ").strip()

        if choice == "1":
            # Run crawler
            print("\n" + "=" * 60)

            # Ask about clearing the index
            print("🗑️  Index Management:")
            print("   - Press Enter to ADD to existing index (default)")
            print("   - Type 'clear' to CLEAR index before indexing (fresh start)")
            clear_choice = input("Index mode: ").strip().lower()

            if clear_choice == "clear":
                print("\n⚠️  WARNING: This will DELETE all existing vectors in the 'smartdrive' namespace!")
                confirm = input("Are you sure? Type 'yes' to confirm: ").strip().lower()
                if confirm == "yes":
                    print("🗑️  Clearing index...")
                    try:
                        index.delete(delete_all=True, namespace="smartdrive")
                        print("✅ Index cleared!\n")
                    except Exception as e:
                        # If namespace doesn't exist yet, that's fine
                        if "Namespace not found" in str(e) or "404" in str(e):
                            print("ℹ️  Namespace doesn't exist yet (this is normal for first run)\n")
                        else:
                            print(f"⚠️  Clear failed: {e}\n")
                else:
                    print("❌ Clear cancelled, will add to existing index\n")
            else:
                print("✅ Will add to existing index (default)\n")

            # Ask about ZIP file handling
            print("=" * 60)
            print("📦 ZIP File Handling:")
            print("   - Press Enter to LIST zip contents (default, faster)")
            print("   - Type 'extract' to EXTRACT and index files inside zips (slower)")
            zip_choice = input("ZIP handling: ").strip().lower()

            if zip_choice == "extract":
                EXTRACT_ZIP_CONTENTS = True
                print("✅ Will extract and index ZIP contents\n")
            else:
                EXTRACT_ZIP_CONTENTS = False
                print("✅ Will list ZIP contents only (default)\n")

            print("=" * 60)
            print("📋 File limit options:")
            print("   - Press Enter for NO LIMIT (process all files)")
            print("   - Or enter a number (e.g., 50 for testing)")
            limit_input = input("File limit: ").strip()

            if limit_input == "":
                max_files = None
                print("\n✅ No limit set - will process all files\n")
            else:
                try:
                    max_files = int(limit_input)
                    print(f"\n✅ Limit set to {max_files} files\n")
                except ValueError:
                    print("\n⚠️ Invalid input, defaulting to no limit\n")
                    max_files = None

            files = list_documents_folder(token, max_files=max_files, interactive=True)
            break

        elif choice == "2":
            # Reset cache
            if has_cache:
                print(f"\n⚠️  This will delete {len(skip_cache)} cached folder choice(s).")
                confirm = input("Are you sure? [y/N]: ").strip().lower()
                if confirm in ['y', 'yes']:
                    if FOLDER_SKIP_CACHE_FILE.exists():
                        FOLDER_SKIP_CACHE_FILE.unlink()
                    print("✅ Folder choices reset!\n")
                    skip_cache = {}
                    has_cache = False
                else:
                    print("❌ Cancelled\n")
            else:
                print("\n⚠️  No cached folder choices to reset.\n")

        elif choice == "3":
            # View/edit cache
            if has_cache:
                print("\n" + "=" * 60)
                print("📂 Cached Folder Choices:")
                print("=" * 60)
                for idx, (folder_path, decision) in enumerate(skip_cache.items(), 1):
                    if decision == "process":
                        status = "✅ PROCESS"
                    elif decision == "skip":
                        status = "⏭️  SKIP"
                    else:
                        status = "📋 LIST-ONLY"
                    print(f"{idx}. {status} - {folder_path}")
                print("=" * 60)

                print("\nOptions:")
                print("  - Enter folder number to cycle through modes (process → list-only → skip → process)")
                print("  - Type 'delete #' to remove a cached choice (e.g., 'delete 3')")
                print("  - Press Enter to go back")

                edit_choice = input("\nYour choice: ").strip().lower()

                if edit_choice == "":
                    print()
                    continue
                elif edit_choice.startswith("delete "):
                    try:
                        num = int(edit_choice.split()[1])
                        folder_to_delete = list(skip_cache.keys())[num - 1]
                        del skip_cache[folder_to_delete]
                        save_folder_skip_cache(skip_cache)
                        print(f"✅ Removed cached choice for: {folder_to_delete}\n")
                        has_cache = len(skip_cache) > 0
                    except (IndexError, ValueError):
                        print("❌ Invalid number\n")
                else:
                    try:
                        num = int(edit_choice)
                        folder_to_toggle = list(skip_cache.keys())[num - 1]
                        current = skip_cache[folder_to_toggle]
                        # Cycle through: process -> list-only -> skip -> process
                        if current == "process":
                            new_value = "list-only"
                            status = "LIST-ONLY"
                        elif current == "list-only":
                            new_value = "skip"
                            status = "SKIP"
                        else:  # skip
                            new_value = "process"
                            status = "PROCESS"
                        skip_cache[folder_to_toggle] = new_value
                        save_folder_skip_cache(skip_cache)
                        print(f"✅ Changed to {status}: {folder_to_toggle}\n")
                    except (IndexError, ValueError):
                        print("❌ Invalid number\n")
            else:
                print("\n⚠️  No cached folder choices to view.\n")

        elif choice == "4":
            print("\n👋 Goodbye!\n")
            exit(0)

        else:
            print("\n❌ Invalid choice, please try again.\n")

    if files:
        upload_to_pinecone(files)

    # Clean up embedding provider sessions
    print("\n🧹 Cleaning up...")
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(embedding_provider.close())
    except Exception:
        pass
