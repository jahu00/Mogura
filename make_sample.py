"""Create a sample CBZ for manual testing."""
import zipfile
from PIL import Image, ImageDraw

colors = ["#e57373", "#64b5f6", "#81c784", "#ffd54f", "#ba68c8"]
with zipfile.ZipFile("sample.cbz", "w") as zf:
    for i, color in enumerate(colors, start=1):
        img = Image.new("RGB", (800, 1200), color)
        d = ImageDraw.Draw(img)
        d.text((350, 560), f"Page {i}", fill="black")
        import io
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        zf.writestr(f"page{i:02d}.jpg", buf.getvalue())
print("Wrote sample.cbz")
