import os
import sys
import unittest

from PIL import Image, ImageDraw


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend import server


class LongImageTilingTests(unittest.TestCase):
    def test_smart_tiles_overlap_and_avoid_text_band(self):
        img = Image.new('RGB', (800, 6200), 'white')
        draw = ImageDraw.Draw(img)
        draw.rectangle([180, 2920, 620, 3060], fill='black')
        draw.text((220, 2965), 'ANGER SO SHARP', fill='white')

        tiles = server._build_vertical_tiles(img, 3000)
        ranges = [(y, h) for y, h, _ in tiles]

        self.assertGreaterEqual(len(ranges), 3)
        first_y, first_h = ranges[0]
        second_y, _ = ranges[1]
        first_end = first_y + first_h

        self.assertEqual(first_y, 0)
        self.assertLess(first_end, 3000)
        self.assertLess(second_y, first_end)
        self.assertGreaterEqual(first_end - second_y, 1)

    def test_dedupe_tree_paragraphs_removes_overlapped_duplicate(self):
        tree = {
            'side': 'original',
            'paragraphs': [
                {
                    'para_index': 0,
                    'text': 'ANGER SO SHARP',
                    'bounds_px': (200, 2920, 610, 3060),
                    'items': [],
                },
                {
                    'para_index': 1,
                    'text': 'ANGER SO SHARP',
                    'bounds_px': (202, 2924, 612, 3064),
                    'items': [],
                },
                {
                    'para_index': 2,
                    'text': 'IT FEELS EERIE',
                    'bounds_px': (210, 3180, 590, 3290),
                    'items': [],
                },
            ],
        }

        meta = server._dedupe_tree_paragraphs(tree, 800, 6200)

        self.assertEqual(meta['removed'], 1)
        self.assertEqual(
            [p['text'] for p in tree['paragraphs']],
            ['ANGER SO SHARP', 'IT FEELS EERIE'],
        )
        self.assertEqual([p['para_index'] for p in tree['paragraphs']], [0, 1])


if __name__ == '__main__':
    unittest.main()
