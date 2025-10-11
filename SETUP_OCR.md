# OCR Setup for SmartDrive MCP

## Built-in OCR (EasyOCR)

**Good news!** SmartDrive now includes **built-in OCR** with no external dependencies required!

### How It Works

SmartDrive uses **EasyOCR**, a pure Python OCR solution that:
- ✅ Works out of the box - no external software needed
- ✅ Automatically downloads AI models on first use (~100MB)
- ✅ Supports scanned PDFs and images with text
- ✅ Works on all platforms (Windows, Mac, Linux)

### First Run

The first time you process a scanned PDF or image:
```
🔍 Loading OCR model (first time only, may take a moment)...
```

The OCR model will be downloaded to `~/.EasyOCR/model/` (about 100MB). This only happens once.

### Supported Formats

OCR is automatically applied to:
- **Scanned PDFs** - PDFs that are images with text (not extractable)
- **Images** - PNG, JPEG, TIFF, BMP, GIF files with text

### Performance Notes

- **CPU Mode**: EasyOCR runs in CPU mode for maximum compatibility
- **Speed**: Takes a few seconds per page for OCR processing
- **Accuracy**: Very good accuracy for printed English text

## Advanced: Using Tesseract (Optional)

If you need faster OCR or better performance, you can optionally install Tesseract:

### Why Use Tesseract?
- ⚡ 2-3x faster than EasyOCR
- 🎯 Better for document scanning use cases
- 🌍 More language support

### Windows Installation

1. **Download Tesseract**
   - Go to: https://github.com/UB-Mannheim/tesseract/wiki
   - Download the latest Windows installer (e.g., `tesseract-ocr-w64-setup-v5.3.x.exe`)

2. **Install Tesseract**
   - Run the installer
   - Note the installation path (usually `C:\Program Files\Tesseract-OCR`)

3. **Configure SmartDrive to Use Tesseract**

   Set this environment variable in your `.env` file:
   ```
   TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
   ```

When Tesseract is configured, SmartDrive will use it instead of EasyOCR for faster processing.

## Summary

**Default (Built-in)**: EasyOCR - works everywhere, no setup needed
**Optional Upgrade**: Tesseract - faster, requires installation

Both work great! Start with the built-in EasyOCR and upgrade to Tesseract only if you need the speed boost.
