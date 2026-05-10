import sys, os, shutil, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO)
from services.ocr_service import OCRService

srv = OCRService()
img_path = 'uploads/1/eeb8a509731948639f0c8b30be477cbd_page_020.png'
output_dir = 'uploads/1/imgs/_test999'
os.makedirs(output_dir, exist_ok=True)

result = srv.recognize(img_path, output_dir=output_dir)
print('MD len:', len(result.get('markdown_text', '')))
print('Output dir:', os.listdir(output_dir))
print('Has imgs:', 'img_in_image_box' in str(os.listdir(output_dir)))

# Clean up
for f in os.listdir(output_dir):
    fp = os.path.join(output_dir, f)
    if os.path.isfile(fp):
        os.remove(fp)
os.rmdir(output_dir)
