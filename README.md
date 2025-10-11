![SmartDrive Logo](logo.png)

# SmartDrive 🧠☁️

**Semantic search for your OneDrive, powered by local embeddings and Pinecone.**

SmartDrive is an MCP (Model Context Protocol) server that brings intelligent semantic search to your Microsoft OneDrive documents. Ask Claude to find "tax forms" and it'll surface your 1099s, W-2s, and related docs—even if those exact words aren't in the filename.

Built with **zero API costs** for embeddings (100% local), making it accessible for everyone.

---

## 🔥 Features

- **Semantic Search**: Natural language queries across your OneDrive
- **Local Embeddings**: Free, fast sentence-transformers (no OpenAI costs)
- **Privacy-First**: Your documents stay in your OneDrive; only embeddings are stored
- **MCP Integration**: Works natively with Claude Desktop (and Open WebUI soon)
- **Document Support**: PDFs, Word docs (.docx), plain text files
- **Easy Setup**: Device code auth—no complex Azure app config

---

## 📦 Installation

### Prerequisites

- Python 3.10+
- Microsoft 365 account with OneDrive
- Pinecone account (free tier works)
- Claude Desktop

### Setup

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
   - Dimensions: `384`
   - Metric: `cosine`
   - Vector type: `dense`
   - Copy your **API Key** and **Index Host**

5. **Configure `.env`**
   ```env
   PINECONE_API_KEY=your_pinecone_api_key
   PINECONE_INDEX_NAME=smartdrive
   PINECONE_HOST=smartdrive-xxxxx.svc.aped-xxxx-xxxx.pinecone.io
   
   MICROSOFT_CLIENT_ID=your_azure_client_id
   MICROSOFT_TENANT_ID=consumers
   ```

6. **Index your OneDrive**
   ```bash
   python onedrive_crawler.py
   ```
   - Follow the device code authentication prompts
   - Currently indexes the `/Documents` folder (first 50 files for testing)

7. **Add to Claude Desktop**

   Edit `%APPDATA%\Claude\claude_desktop_config.json`:
   
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

## 🚀 Usage

In Claude Desktop, simply ask:

- "Search my OneDrive for resume"
- "Find tax documents"
- "Show me project proposals from this year"

SmartDrive will semantically search your indexed documents and return relevant results with file paths, modification dates, and content previews.

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
1. `onedrive_crawler.py` authenticates via Microsoft Graph API
2. Extracts text from documents (PDF, DOCX, TXT)
3. Generates embeddings using `all-MiniLM-L6-v2` (local)
4. Stores vectors + metadata in Pinecone

**Search Flow:**
1. Claude sends query to MCP server
2. Query embedded locally
3. Pinecone returns top-k similar vectors
4. Results formatted with file metadata

---

## 🛠️ Configuration

### Indexing Options

Edit `onedrive_crawler.py` to customize:

- **File limit**: Change `max_files=50` to index more/fewer files
- **Folders**: Modify the folder path from `/Documents` to any OneDrive folder
- **File types**: Add support for Excel, images (OCR), etc.

### Embedding Model

Currently uses `all-MiniLM-L6-v2` (384 dimensions). To use a different model:

1. Update model name in both `onedrive_crawler.py` and `smartdrive_server.py`
2. Recreate Pinecone index with matching dimensions
3. Re-index your documents

---

## 🔮 Roadmap

- [ ] Remove file indexing limits
- [ ] Recursive folder crawling
- [ ] Excel (.xlsx) support
- [ ] Image OCR support (via Tesseract)
- [ ] Incremental sync (only index changed files)
- [ ] Open WebUI integration
- [ ] Token caching for auth
- [ ] Batch processing for large OneDrive libraries
- [ ] Support for SharePoint/Teams files

---

## 🤝 Contributing

Built for the community, by the community. PRs welcome!

**Areas we'd love help with:**
- Additional file format support
- Performance optimizations
- Better error handling
- Documentation improvements
- Open WebUI integration

---

## 📄 License

MIT License - do whatever you want with this, just keep it free and accessible.

---

## 🙏 Acknowledgments

- Built with [MCP](https://modelcontextprotocol.io/) by Anthropic
- Embeddings via [sentence-transformers](https://www.sbert.net/)
- Vector storage by [Pinecone](https://www.pinecone.io/)
- Microsoft Graph API for OneDrive access

---

## 💬 Support

Questions? Issues? Open a GitHub issue or reach out.

Built with 🔥 by [@1818TusculumSt](https://github.com/1818TusculumSt)

---

**Remember:** This tool is designed to be cost-free for embeddings. Keep it that way for the community. 💪
