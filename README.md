![SmartDrive Logo](logo.png)

# SmartDrive 🧠☁️

**Semantic search for your entire OneDrive, powered by Pinecone vector search.**

SmartDrive is an MCP (Model Context Protocol) server that brings intelligent semantic search to your Microsoft OneDrive documents. Ask Claude to find "tax forms" and it'll surface your 1099s, W-2s, and related docs—even if those exact words aren't in the filename.

---

## 🔥 Features

### Core Capabilities
- **Semantic Search**: Natural language queries across your entire OneDrive
- **Flexible Embeddings**: Choose local (free), Pinecone inference, Voyage AI, or custom API
- **Incremental Sync**: Smart detection of unchanged files - only indexes new/modified content
- **New Folder Detection**: Optionally check for new folders before crawling (configurable)
- **Privacy-First**: Your documents stay in your OneDrive; only embeddings are stored
- **MCP Integration**: Works natively with Claude Desktop
- **Interactive Folder Selection**: Choose which folders to index, skip what you don't need
- **Smart Caching**: Remembers authentication and folder choices between runs

### Document Support
- **Documents**: PDF (with OCR for scanned docs!), DOCX, DOC
- **Presentations**: PPTX (legacy .ppt not supported - convert to .pptx)
- **Spreadsheets**: XLSX, XLSM, CSV
- **Data**: JSON, TXT, Markdown (MD)
- **Images**: PNG, JPG, TIFF, BMP, GIF (with OCR)
- **Archives**: ZIP files (list contents or extract and index)
- **Graceful Fallbacks**: Corrupted/malformed files indexed with metadata only

### OCR & Document Intelligence
- **Local OCR**: EasyOCR for scanned PDFs and images (free, no external software!)
- **Cloud OCR**: Azure Computer Vision for 10-20x faster processing (optional)
- **Azure Document Intelligence**: Premium AI for forms, tables, invoices, receipts with handwriting support
- **Flexible Modes**: Never, selective (smart detection), or always use Document Intelligence
- **No Setup Required**: Local OCR works out of the box
- **Smart Detection**: Automatically detects scanned PDFs and applies OCR

---

## 📦 Installation

### Prerequisites

- Python 3.10+
- Microsoft 365 account with OneDrive
- Pinecone account (free tier works)
- Claude Desktop

### Quick Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/1818TusculumSt/smartdrive-mcp.git
   cd smartdrive-mcp
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create Azure App Registration**
   - Go to [Azure Portal](https://portal.azure.com) → **App Registrations** → **New registration**
   - Name: `SmartDrive MCP`
   - Supported accounts: **Personal Microsoft accounts only**
   - Redirect URI: Leave blank
   - After creation, go to **API permissions** → Add:
     - `Files.Read.All`
     - `User.Read`
   - Go to **Authentication** → Enable **Allow public client flows**
   - Copy **Application (client) ID** and **Directory (tenant) ID**

4. **Create Pinecone Index**
   - Go to [Pinecone](https://www.pinecone.io/) → Create Index
   - Name: `smartdrive`
   - Dimensions: Choose based on your embedding provider:
     - `384` for local (all-MiniLM-L6-v2)
     - `1024` for Pinecone inference (llama-text-embed-v2)
     - `2048` for Voyage AI (voyage-3-large)
   - Metric: `cosine`
   - Vector type: `dense`
   - Copy your **API Key** and **Index Host**

5. **Configure `.env`**

   Copy `.env.example` to `.env` and fill in your values:

   ```env
   PINECONE_API_KEY=your_pinecone_api_key
   PINECONE_INDEX_NAME=smartdrive
   PINECONE_HOST=smartdrive-xxxxx.svc.aped-xxxx-xxxx.pinecone.io

   MICROSOFT_CLIENT_ID=your_azure_client_id
   MICROSOFT_TENANT_ID=consumers

   # Optional: Choose your embedding provider (local, pinecone, voyage, or api)
   EMBEDDING_PROVIDER=local
   EMBEDDING_MODEL=all-MiniLM-L6-v2

   # For Voyage AI (32K token context, 2048 dims, $0.10/1M tokens):
   # EMBEDDING_PROVIDER=voyage
   # VOYAGE_API_KEY=your_voyage_api_key
   # VOYAGE_MODEL=voyage-3-large
   ```

6. **Index your OneDrive**
   ```bash
   python onedrive_crawler.py
   ```

   You'll see an interactive menu:
   ```
   ============================================================
   📋 SmartDrive Crawler - Main Menu
   ============================================================
   1. Run crawler (use cached folder choices)
   2. Reset folder choices and start fresh
   3. View/edit cached folder choices
   4. Exit
   ```

   - First time: Choose option 1
   - Authenticate with your Microsoft account (device code flow)
   - Choose ZIP handling (list contents or extract - default is list)
   - Set file limit (or press Enter for no limit to index everything)
   - Answer Yes/No for each folder as the crawler discovers them
   - Use "always yes" or "skip always" to remember your choices!

7. **Add to Claude Desktop**

   Edit `%APPDATA%\Claude\claude_desktop_config.json` (Windows) or `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac):

   ```json
   {
     "mcpServers": {
       "smartdrive": {
         "command": "python",
         "args": [
           "C:\\path\\to\\smartdrive-mcp\\smartdrive_server.py"
         ],
         "env": {
           "PINECONE_API_KEY": "your_pinecone_api_key",
           "PINECONE_INDEX_NAME": "smartdrive",
           "PINECONE_HOST": "smartdrive-xxxxx.svc.aped-xxxx-xxxx.pinecone.io"
         }
       }
     }
   }
   ```

8. **Restart Claude Desktop**

---

## 🐳 Docker Setup (Recommended)

**Why Docker?**
- ✅ **Zero system pollution** - isolated environment
- ✅ **No dependency conflicts** - all Python packages contained
- ✅ **Reproducible** - works identically everywhere
- ✅ **Easy cleanup** - remove container, done
- ✅ **Persistent cache** - OAuth tokens and folder choices survive restarts

### Docker Quick Start

1. **Clone and configure**
   ```bash
   git clone https://github.com/1818TusculumSt/smartdrive-mcp.git
   cd smartdrive-mcp
   cp .env.example .env
   # Edit .env with your credentials
   ```

2. **Build and run**
   ```bash
   docker-compose up -d
   ```

3. **Index your OneDrive (first time)**
   ```bash
   docker-compose run --rm smartdrive-mcp python onedrive_crawler.py
   ```

4. **Subsequent runs** (use cached folder choices)
   ```bash
   docker-compose run --rm smartdrive-mcp
   ```

### Docker Commands

```bash
# Build the image
docker-compose build

# Run crawler interactively
docker-compose run --rm smartdrive-mcp

# View logs
docker-compose logs -f

# Stop container
docker-compose down

# Rebuild after code changes
docker-compose build --no-cache

# Clean up everything (keeps .env and cache files)
docker-compose down --rmi all
```

### Cache Persistence

Docker automatically mounts these cache files from your host:
- `~/.smartdrive_token_cache.json` - OAuth tokens (survives restarts)
- `~/.smartdrive_folder_skip_cache.json` - Folder choices (remembers skip/process decisions)
- `~/.EasyOCR/` - OCR models (avoids re-downloading 100MB)

### Using with Claude Desktop

Point Claude Desktop to the Docker container's MCP server:

```json
{
  "mcpServers": {
    "smartdrive": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--env-file",
        "/path/to/smartdrive-mcp/.env",
        "smartdrive-mcp",
        "python",
        "smartdrive_server.py"
      ]
    }
  }
}
```

---

## 🚀 Usage

### In Claude Desktop

Simply ask Claude natural language questions:

- "Search my OneDrive for resume"
- "Find tax documents from 2024"
- "Show me project proposals"
- "Where are my meeting notes about the Q4 budget?"

SmartDrive will semantically search your indexed documents and return relevant results with file paths, modification dates, and content previews.

### Interactive Crawler Menu

The crawler has a full menu system for managing your indexing:

**Option 1: Run Crawler**
- Choose ZIP handling (list or extract contents)
- Set file limit (or no limit for full index)
- Interactive folder selection
- Beautiful progress tracking with OCR status

**Option 2: Reset Folder Choices**
- Clear all cached folder preferences
- Start fresh with folder selection

**Option 3: View/Edit Cached Folder Choices**
- See all your saved folder decisions
- Toggle folders between SKIP and PROCESS
- Delete specific cached choices

### Processing Summary

After crawling, you'll get a detailed summary:

```
============================================================
📊 Processing Summary:
============================================================
✅ Successfully extracted: 847 files

❌ Failed extractions (3):
   • corrupted_report.xlsx (.xlsx)
   • malformed_doc.pdf (.pdf)

⚠️ Unsupported file types (5):
   • .mp4: 2 file(s)
   • .zip: 3 file(s)
============================================================
```

---

## 🏗️ Architecture

```
┌─────────────────┐
│  Claude Desktop │
└────────┬────────┘
         │ MCP Protocol
         ▼
┌─────────────────────┐
│ smartdrive_server.py│
│  (MCP Server)       │
└────────┬────────────┘
         │
         ├──► sentence-transformers (local embeddings)
         │
         └──► Pinecone (vector storage)
```

**Crawler Flow:**
1. `onedrive_crawler.py` authenticates via Microsoft Graph API (cached for future runs)
2. Recursively crawls your Documents folder
3. Extracts text from documents (PDF, DOCX, DOC, PPTX, XLSX, CSV, JSON, Markdown, images)
4. Applies OCR to scanned PDFs and images automatically
5. Generates embeddings using configured provider
6. Stores vectors + metadata in Pinecone

**Search Flow:**
1. Claude sends query to MCP server
2. Query embedded using configured provider
3. Pinecone returns top-k similar vectors
4. Results formatted with file metadata

---

## 🛠️ Configuration

### Embedding Providers

SmartDrive supports four embedding providers:

#### Local (Free, Private)
```env
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=all-MiniLM-L6-v2
```
- ✅ Runs on your machine (sentence-transformers)
- ✅ No API calls or costs
- ✅ Complete privacy
- 📊 384 dimensions, ~512 token context

#### Voyage AI (Recommended for Large Documents) 🚀
```env
EMBEDDING_PROVIDER=voyage
VOYAGE_API_KEY=your_voyage_api_key
VOYAGE_MODEL=voyage-3-large
```
- ✅ **32,000 token context** (128K chars) - embed entire 50+ page PDFs!
- ✅ **2048 dimensions** for maximum quality
- ✅ Fast cloud API, optimized for long documents
- 💰 **$0.10 per 1M tokens** (~$0.10-0.50 for 600 typical files)
- 🎯 Best for: Academic papers, books, reports, large documents

#### Pinecone Inference
```env
EMBEDDING_PROVIDER=pinecone
EMBEDDING_MODEL=llama-text-embed-v2
```
- Hosted embedding models via Pinecone
- 1024 dimensions (high quality)
- Requires Pinecone API key
- Access to specialized models

#### Custom API
```env
EMBEDDING_PROVIDER=api
EMBEDDING_API_URL=https://your-api.com/embeddings
EMBEDDING_API_KEY=your_api_key
EMBEDDING_MODEL=your-model-name
```
- OpenAI-compatible API format
- Use any embedding service (OpenAI, Cohere, etc.)
- Self-hosted options supported

### Incremental Sync

SmartDrive intelligently skips unchanged files to save time and API costs:

- ✅ **Pre-extraction check**: Checks Pinecone before downloading/extracting files
- ✅ **Metadata comparison**: Compares file modified date and size
- ✅ **Skip unchanged**: Files that haven't changed are skipped entirely
- ✅ **Update only modified**: Only re-indexes files that changed
- ⚡ **~100x faster** for re-indexing mostly unchanged folders

**New Folder Detection**: When running with cached folder choices, you can optionally check for new folders:
- Press Enter = Skip check (fast, uses cache only)
- Type 'check' = Discover new folders and prompt for each one

### OCR Configuration

SmartDrive supports two OCR methods:

#### Local OCR (EasyOCR - Default)
- **Free** and works out of the box
- Downloads models automatically on first use (~100MB)
- **Speed**: 10-30 seconds per page
- No external dependencies

#### Cloud OCR (Azure Computer Vision - Optional)
Add to your `.env`:
```env
AZURE_VISION_KEY=your_azure_vision_key
AZURE_VISION_ENDPOINT=https://your-region.api.cognitive.microsoft.com/
```

**Benefits:**
- **10-20x faster**: 1-3 seconds per page vs 10-30 seconds
- More accurate OCR results
- No CPU/GPU load on your machine
- **Free tier**: 5,000 pages/month
- **Paid tier**: $1.50 per 1,000 pages (~$0.50-$2 for typical use)

**Setup:**
1. Go to [Azure Portal](https://portal.azure.com)
2. Create "Computer Vision" resource
3. Choose "Free F0" tier (5,000 pages/month) or "Standard S1"
4. Copy your API key and endpoint to `.env`

#### OCR Strict Mode (Optional)
Force Azure OCR only (no EasyOCR fallback):
```env
OCR_STRICT_MODE=true
```

When enabled:
- ✅ Only uses Azure OCR (10-20x faster)
- ❌ Files fail if Azure OCR fails (no slow EasyOCR fallback)
- 💡 Use this for speed when you have Azure credits

SmartDrive will automatically use Azure OCR if credentials are provided, otherwise falls back to local EasyOCR (unless strict mode is enabled).

### Azure Document Intelligence (Advanced)

Azure Document Intelligence (formerly Form Recognizer) is a premium AI service that provides advanced extraction capabilities beyond basic OCR. It's specifically designed for structured documents like forms, invoices, receipts, and tax documents.

**What It Does:**
- **Intelligent form extraction**: Automatically identifies and extracts key-value pairs from forms
- **Table extraction**: Preserves table structure with rows, columns, and cell relationships
- **Handwriting recognition**: Accurately recognizes handwritten text
- **Layout analysis**: Understands document structure (headers, sections, paragraphs)
- **Pre-built models**: Optimized for invoices, receipts, tax forms, ID documents

**Three Operating Modes:**

1. **`never` (default)**: Document Intelligence is disabled
   - Uses standard Azure OCR → EasyOCR fallback chain
   - Fastest and most cost-effective for simple documents

2. **`selective` (smart detection)**: Automatically enabled for specific document types
   - Activates when filenames contain keywords: `tax`, `invoice`, `receipt`, `form`, `w2`, `1099`, `w-2`, `1040`
   - Perfect balance of cost and capability
   - Recommended for mixed document libraries

3. **`always`**: Uses Document Intelligence for ALL documents
   - Maximum extraction quality for every file
   - Higher cost - only use if you need advanced extraction for all documents

**Pricing & Limits:**

**Free Tier (F0):**
- **Cost**: Free
- **Limitations**: Only processes **first 2 pages** of multi-page documents
- **Monthly limit**: 500 pages per month
- **Speed**: 1 transaction per second (TPS)
- **Best for**: Testing, small document sets, or documents that are 1-2 pages

**Standard Tier (S0):**
- **Cost**: **$1.50 per 1,000 pages**
- **Full document processing**: All pages extracted, no page limits
- **No monthly limits**: Pay-per-use
- **Speed**: 15 TPS
- **Typical cost**: ~$0.75 for 500 pages (vs free tier's first-2-pages limitation)
- **Recommended for**: Production use, multi-page documents

**Setup Instructions:**

1. Go to [Azure Portal](https://portal.azure.com)
2. Create a **"Document Intelligence"** resource (or search "Form Recognizer")
3. Choose tier:
   - **Free F0**: Testing or 1-2 page documents only
   - **Standard S0**: Production use with full document extraction
4. After creation, go to **"Keys and Endpoint"**
5. Copy **KEY 1** and **Endpoint URL**
6. Add to your `.env`:

```env
AZURE_FORM_RECOGNIZER_KEY=your_key_here
AZURE_FORM_RECOGNIZER_ENDPOINT=https://your-region.cognitiveservices.azure.com/

# Choose your mode:
USE_DOCUMENT_INTELLIGENCE=selective  # never, selective, or always
```

**Fallback Chain:**

SmartDrive uses a sophisticated fallback system:
1. **Azure Document Intelligence** (if enabled and conditions met)
2. **Azure Computer Vision OCR** (if credentials provided)
3. **EasyOCR** (local, always available)

**Performance:**
- **Processing time**: 5-15 seconds per document (varies with page count and complexity)
- **Timeout**: 2-minute safety timeout prevents hanging on problematic files
- **Progress indicator**: Real-time page-by-page progress for multi-page documents
- **Reliability**: Automatic fallback if service is unavailable or times out

**Best Use Cases:**
- Tax documents (W-2, 1099, 1040 forms)
- Invoices and receipts with complex layouts
- Business forms with structured fields
- Contracts with tables and signatures
- Handwritten notes and forms
- Documents requiring precise table extraction

**Tips:**
- Start with `selective` mode to balance cost and quality
- Use `always` mode only if you need advanced extraction for every document
- Free tier (F0) is fine for testing, but upgrade to S0 for production multi-page documents
- Monitor your usage in Azure Portal to stay within budget

### Indexing Customization

**File Limits:**
- Test with 50-100 files first
- Then press Enter for no limit to index everything

**Folder Selection:**
- Interactive prompts for every folder
- Use "always" options to cache your choices
- Edit choices anytime via the menu (Option 3)

**ZIP File Handling:**
- Default: List contents (fast, searchable by filename and file list)
- Extract: Full text extraction from files inside ZIPs (slower, comprehensive)

---

## 📊 Supported File Formats

| Category | Formats | OCR Support |
|----------|---------|-------------|
| Documents | PDF, DOCX, DOC | ✅ (scanned PDFs) |
| Presentations | PPTX | - |
| Spreadsheets | XLSX, XLSM, XLTX, XLTM, CSV | - |
| Data | JSON, TXT, Markdown (MD) | - |
| Images | PNG, JPG, JPEG, TIFF, BMP, GIF | ✅ |
| Archives | ZIP | List or Extract |

**Note**: Legacy PowerPoint (.ppt) files are not supported. Convert to .pptx for full-text extraction.

---

## 🎯 Best Practices

### For Large OneDrive Libraries (10GB+)

1. **Test First**: Start with 100-file limit
2. **Choose Folders Wisely**: Skip temp folders, downloads, etc.
3. **ZIP Strategy**: Use "list" mode for most ZIPs (faster)
4. **Run Overnight**: Full indexing of large libraries can take hours
5. **Monitor Progress**: OCR shows page-by-page progress

### For Best Search Results

1. **Descriptive Queries**: "Find project proposals from Q4" works better than "proposals"
2. **Use Context**: Include timeframes, topics, or people names
3. **Iterative Search**: Refine based on initial results

### Maintaining Your Index

1. **Re-run Periodically**: Run crawler monthly to catch new files
2. **Cached Choices**: Your folder preferences are saved
3. **Incremental Updates**: Future versions will support smart syncing

---

## 🐛 Troubleshooting

### Common Issues

**"OCR failed" warnings**
- This is expected for some scanned PDFs
- Text extraction falls back to whatever is available
- Most documents work fine

**Excel parsing errors**
- Some complex XLSX files may fail
- CSV is more reliable for data files

**Authentication timeout**
- Tokens are cached - just re-run if expired
- Delete `~/.smartdrive_token_cache.json` to force re-auth

**Slow processing**
- OCR takes 3-10 seconds per page
- Normal for scanned documents
- Progress indicators show it's working

### Need Help?

Open a GitHub issue with:
- Error message (if any)
- File type causing issues
- Steps to reproduce

---

## 🗺️ Roadmap

### Completed ✅
- ✅ Recursive folder crawling
- ✅ Interactive folder selection with caching
- ✅ New folder detection (optional pre-crawl check)
- ✅ Incremental sync (pre-extraction Pinecone check)
- ✅ Excel (.xlsx) support
- ✅ Image OCR support (EasyOCR + Azure Computer Vision)
- ✅ Token caching for auth
- ✅ CSV support
- ✅ JSON support
- ✅ Markdown (.md) support
- ✅ ZIP file handling (list + extract)
- ✅ Scanned PDF OCR with page-by-page progress
- ✅ Progress indicators
- ✅ Comprehensive error reporting
- ✅ Voyage AI embedding support (32K token context!)
- ✅ Pinecone inference with 1024-dim embeddings
- ✅ Graceful fallbacks for corrupted files
- ✅ Azure Document Intelligence integration with three modes (never, selective, always)
- ✅ Image OCR via Document Intelligence (JPG/PNG/TIFF/BMP/GIF)
- ✅ Page-by-page progress indicator for Document Intelligence extraction
- ✅ Smart timeout handling (2-minute) for reliability

### Coming Soon 🚀

#### Incremental Sync Daemon (High Priority)
A true background service for automatic index updates:
- **Microsoft Graph Delta API**: Detects only changed files (adds/updates/deletes)
- **Continuous Background Process**: Runs 24/7, checks every 5-10 minutes
- **Smart State Tracking**: Stores deltaLink tokens to track changes since last sync
- **Deletion Handling**: Automatically removes vectors for deleted files from Pinecone
- **Efficient Processing**: Only indexes what changed - no full re-crawls
- **Proper Daemon**: Not a scheduled script - true background service with logging
- **Estimated complexity**: 3-4 hours implementation (delta API makes this surprisingly doable)
- **Result**: True "set and forget" - your index stays fresh automatically

#### Other Features
- [ ] Open WebUI integration
- [ ] Support for SharePoint/Teams files
- [ ] Configurable crawl depth
- [ ] Custom metadata extraction
- [ ] Multi-language OCR

---

## 🤝 Contributing

Built for the community, by the community. PRs welcome!

**Areas we'd love help with:**
- Performance optimizations
- Incremental sync implementation
- Open WebUI integration
- Documentation improvements
- Unit tests
- Additional file formats (e.g., RTF, ODT)

---

## 📄 License

MIT License - do whatever you want with this, just keep it free and accessible.

---

## 🙏 Acknowledgments

- Built with [MCP](https://modelcontextprotocol.io/) by Anthropic
- Embeddings via [sentence-transformers](https://www.sbert.net/)
- Vector storage by [Pinecone](https://www.pinecone.io/)
- Microsoft Graph API for OneDrive access
- OCR powered by [EasyOCR](https://github.com/JaidedAI/EasyOCR)
- PDF processing via [PyMuPDF](https://pymupdf.readthedocs.io/)

---

## 💬 Support

Questions? Issues? Open a GitHub issue or reach out.

Built with 🔥 by [@1818TusculumSt](https://github.com/1818TusculumSt)

---

**Remember:** This tool is designed to be cost-free for embeddings. Keep it that way for the community. 💪
