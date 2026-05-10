import sys, os, shutil, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO)

# Simulate startup pre-init
from services.ocr_service import OCRService, _global_pipeline
srv1 = OCRService()
pipe = srv1._get_pipeline()
print("Pipeline OK:", type(pipe).__name__, "cached:", _global_pipeline is not None)

# Now simulate a second call (like _process_ocr_sync)
srv2 = OCRService()
img_path = 'uploads/1/eeb8a509731948639f0c8b30be477cbd_page_020.png'
output_dir = 'uploads/1/imgs/_test_reuse'
os.makedirs(output_dir, exist_ok=True)

result2 = srv2.recognize(img_path, output_dir=output_dir)
print("MD len:", len(result2.get('markdown_text', '')))
print("img_error:", result2.get('image_error'))
print("Files:", os.listdir(output_dir))

# Clean
for f in os.listdir(output_dir):
    fp = os.path.join(output_dir, f)
    if os.path.isfile(fp): os.remove(fp)
os.rmdir(output_dir)
