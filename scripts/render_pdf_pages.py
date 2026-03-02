# scripts/render_pdf_pages.py
import os, sys
import fitz  # PyMuPDF

def main():
    pdf_path = os.environ.get("PDF_FILE")
    if not pdf_path:
        print("PDF_FILE を set してください。例: set \"PDF_FILE=inputs\\sample.pdf\"")
        sys.exit(1)

    out_dir = os.environ.get("IMG_DIR", "runs\\images")
    os.makedirs(out_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    # 2倍ズーム（細部が見やすい）
    mat = fitz.Matrix(2, 2)

    saved = []
    for i in range(len(doc)):
        page = doc[i]
        pix = page.get_pixmap(matrix=mat, alpha=False)  # page.get_pixmap() :contentReference[oaicite:3]{index=3}
        out_path = os.path.join(out_dir, f"page_{i+1:03d}.png")
        pix.save(out_path)
        saved.append(out_path)

    print("\n".join(saved))

if __name__ == "__main__":
    main()
