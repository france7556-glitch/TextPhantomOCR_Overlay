from PIL import Image, ImageDraw
import sys
import os

img = Image.new("RGB", (800, 6000), "white")
draw = ImageDraw.Draw(img)

# add blocks with text
draw.rectangle([100, 500, 700, 800], fill="black")
draw.rectangle([100, 3500, 700, 3800], fill="black")
draw.rectangle([100, 5500, 700, 5800], fill="black")

# add english text directly without using a font file
try:
    draw.text((150, 600), "This is the top text in chunk 1.", fill="white", align="center", font_size=40)
    draw.text((150, 3600), "This is the middle text in chunk 2.", fill="white", align="center", font_size=40)
    draw.text((150, 5600), "This is the bottom text in chunk 3.", fill="white", align="center", font_size=40)
except Exception:
    draw.text((150, 600), "This is the top text in chunk 1.", fill="white", align="center")
    draw.text((150, 3600), "This is the middle text in chunk 2.", fill="white", align="center")
    draw.text((150, 5600), "This is the bottom text in chunk 3.", fill="white", align="center")

test_img_path = os.path.join(os.path.dirname(__file__), "long_test.jpg")
img.save(test_img_path, format="JPEG")
print("Saved long_test.jpg, size:", img.size)

# Setup context for process_image_path
import server
import lens_core

# Mock or check Lens API output
try:
    res = server.process_image_path(test_img_path, "th", "lens_text", None)
    print("Finished successfully!")
    print("AiTextFull:", res.get("AiTextFull"))
    print("Original paragraphs count:", len(res.get("original", {}).get("originalTree", {}).get("paragraphs", [])))
    if res.get("imageDataUri"):
        print("imageDataUri length:", len(res["imageDataUri"]))
    else:
        print("NO imageDataUri found!")
except Exception as e:
    print("Error during processing:", e)
    import traceback
    traceback.print_exc()

