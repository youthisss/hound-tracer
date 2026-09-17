from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hound.presentation import DOG_MARK


def main():
    root = Path(__file__).resolve().parents[1] / "docs" / "assets"
    width, height = len(DOG_MARK[0]), len(DOG_MARK) * 2
    image = Image.new("RGBA", (width, height))
    rectangles = []
    for row, line in enumerate(DOG_MARK):
        for x, character in enumerate(line):
            for half in range(2):
                if character == "█" or character == ("▀" if half == 0 else "▄"):
                    y = row * 2 + half
                    image.putpixel((x, y), (255, 255, 255, 255))
                    rectangles.append(f'<rect x="{x}" y="{y}" width="1" height="1"/>')
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        'shape-rendering="crispEdges" role="img" aria-labelledby="title">\n'
        '  <title id="title">Hound-Tracer terminal mascot</title>\n'
        '  <g fill="#fff">\n    ' + '\n    '.join(rectangles) + '\n  </g>\n</svg>\n'
    )
    (root / "hound-mark.svg").write_text(svg, encoding="utf-8")
    for size in (16, 24, 32, 64, 512):
        target_width = max(1, round(size * 0.75))
        target_height = max(1, round(target_width * height / width))
        mark = image.resize((target_width, target_height), Image.Resampling.NEAREST)
        canvas = Image.new("RGBA", (size, size))
        canvas.paste(mark, ((size - target_width) // 2, (size - target_height) // 2))
        if size == 512:
            background = Image.new("RGBA", canvas.size, "black")
            background.alpha_composite(canvas)
            background.convert("RGB").save(root / "hound-mark-preview.png")
        else:
            canvas.save(root / f"hound-mark-{size}.png")


if __name__ == "__main__":
    main()
