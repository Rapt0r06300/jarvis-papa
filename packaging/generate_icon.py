from pathlib import Path

from PIL import Image, ImageDraw


OUTPUT = Path(__file__).with_name("jarvis.ico")
SIZE = 256
image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)

# Calm blue app tile.
draw.rounded_rectangle((8, 8, 248, 248), radius=54, fill=(23, 105, 189, 255))
draw.ellipse((45, 34, 211, 211), fill=(235, 246, 255, 255))

# Hair and face: intentionally stylised, recognisable at small Windows icon sizes.
draw.ellipse((76, 53, 180, 184), fill=(66, 43, 38, 255))
draw.ellipse((91, 67, 165, 169), fill=(239, 194, 163, 255))
draw.pieslice((82, 48, 176, 137), start=175, end=355, fill=(77, 49, 42, 255))
draw.ellipse((107, 106, 116, 114), fill=(91, 65, 52, 255))
draw.ellipse((140, 106, 149, 114), fill=(91, 65, 52, 255))
draw.arc((113, 127, 145, 151), start=15, end=165, fill=(161, 74, 81, 255), width=4)

# Voice bars.
for x, height in ((91, 21), (108, 34), (125, 45), (142, 34), (159, 21)):
    y = 206 - height // 2
    draw.rounded_rectangle((x, y, x + 8, y + height), radius=4, fill=(255, 255, 255, 235))

image.save(
    OUTPUT,
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print(OUTPUT)
