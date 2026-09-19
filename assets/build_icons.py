"""Convert the supplied logo into app assets; run from any working directory."""
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def main():
    resources = ROOT / 'resources'
    resources.mkdir(exist_ok=True)
    for source, destination in (
        ('logo-icon.png', 'icon.png'),
        ('logo.png', 'icon-about.png'),
    ):
        with Image.open(ROOT / 'assets' / source) as image:
            image.convert('RGBA').resize(
                (256, 256), Image.Resampling.LANCZOS,
            ).save(resources / destination)
    with Image.open(ROOT / 'assets' / 'logo-icon.png') as image:
        image.convert('RGBA').save(
            resources / 'icon.ico', format='ICO',
            sizes=[(size, size) for size in ICON_SIZES],
        )
    print('Generated app, About, and Windows icons in resources/.')


if __name__ == '__main__':
    main()
