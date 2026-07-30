from PIL import Image, ImageDraw, ImageFont
import math

# Standard Android TV Leanback banner: 320x180 -> use 1280x720 (4x)
W, H = 1280, 720

img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Gradient background
for y in range(H):
    r = int(0x10 + (0x00 - 0x10) * y / H)
    g = int(0x20 + (0x6F - 0x20) * y / H)
    b = int(0x27 + (0x5C - 0x27) * y / H)
    draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

# Accent gradient overlay (teal)
for y in range(H):
    alpha = int(40 * (1 - abs(y - H/2) / (H/2)))
    draw.line([(0, y), (W, y)], fill=(0, 105, 92, alpha))

# Bottom accent line
accent_start = H - 12
for y in range(accent_start, H):
    ratio = (y - accent_start) / (H - accent_start)
    r = int(0x00 + (0x10 - 0x00) * ratio)
    g = int(0xBF + (0x20 - 0xBF) * ratio)
    b = int(0xA5 + (0x27 - 0xA5) * ratio)
    draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

# --- Hexagon icon (system / update symbol) ---
def draw_hexagon(cx, cy, size, color, alpha, width=3):
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    pts = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        pts.append((cx + size * math.cos(angle), cy + size * math.sin(angle)))
    overlay_draw.polygon(pts, outline=color + (alpha,), width=width)
    img.paste(overlay, (0, 0), overlay)

cx_icon, cy_icon = 160, 360
draw_hexagon(cx_icon, cy_icon, 100, (0, 191, 165), 80, 4)
draw_hexagon(cx_icon, cy_icon, 75, (0, 191, 165), 50, 3)

# Inner filled hexagon
pts_inner = []
for i in range(6):
    angle = math.radians(60 * i - 30)
    pts_inner.append((cx_icon + 40 * math.cos(angle), cy_icon + 40 * math.sin(angle)))
draw.polygon(pts_inner, fill=(0, 191, 165, 50), outline=(0, 191, 165, 80), width=2)

# Upward arrow inside hexagon (update symbol)
arrow = [
    (cx_icon, cy_icon - 42),
    (cx_icon - 22, cy_icon - 5),
    (cx_icon - 8, cy_icon - 5),
    (cx_icon - 8, cy_icon + 35),
    (cx_icon + 8, cy_icon + 35),
    (cx_icon + 8, cy_icon - 5),
    (cx_icon + 22, cy_icon - 5),
]
draw.polygon(arrow, fill=(0, 191, 165, 130))

# --- Load fonts ---
font_paths = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
]

title_font = None
sub_font = None
for fp in font_paths:
    try:
        title_font = ImageFont.truetype(fp, 72)
        sub_font = ImageFont.truetype(fp, 28)
        break
    except:
        continue

if title_font is None:
    title_font = ImageFont.load_default()
    sub_font = ImageFont.load_default()

# --- Text (left-aligned, properly spaced) ---
draw.text((300, 240), "Preinstall", fill=(255, 255, 255, 235), font=title_font)
draw.text((300, 320), "Manager", fill=(0, 191, 165, 230), font=title_font)

# Subtitle - smaller, safe position
draw.text((300, 420), "System app update manager", fill=(200, 200, 200, 140), font=sub_font)

# --- Decorative elements (right side) ---
def draw_circle(x, y, radius, color, alpha):
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        fill=color + (alpha,)
    )
    img.paste(overlay, (0, 0), overlay)

draw_circle(1040, 200, 80, (0, 191, 165), 25)
draw_circle(1100, 280, 40, (0, 191, 165), 20)
draw_circle(980, 350, 30, (0, 191, 165), 15)

# Small dots pattern
for i in range(6):
    draw_circle(1180, 120 + i * 40, 3 if i % 2 == 0 else 5, (0, 191, 165), 30)

for i in range(4):
    draw_circle(1060 + i * 35, 520, 4, (0, 191, 165), 20)

# Tech lines
for x in range(500, 700, 25):
    draw.line([(x, 510), (x + 12, 510)], fill=(0, 191, 165, 18), width=2)
for x in range(900, 1100, 20):
    draw.line([(x, 620), (x + 10, 620)], fill=(0, 191, 165, 12), width=1)

img.save("d:\\PreinstallManager\\app\\src\\main\\res\\drawable\\banner.png")
print("Leanback banner saved (1280x720)")
