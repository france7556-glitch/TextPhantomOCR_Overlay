import os
import sys
import unittest

from PIL import Image, ImageDraw


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend import server


class LongImageTilingTests(unittest.TestCase):
    def test_default_tile_height_keeps_standard_manhwa_page_whole(self):
        img = Image.new('RGB', (800, 5000), 'white')
        tiles = server._build_vertical_tiles(img, server.TP_TILE_MAX_H)

        self.assertEqual([(y, h) for y, h, _ in tiles], [(0, 5000)])

    def test_default_tile_overlap_covers_large_speech_bubble_text(self):
        self.assertGreaterEqual(server.TP_TILE_OVERLAP_PX, 360)

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

    def test_translated_text_is_patched_onto_original_geometry(self):
        original_tree = {
            'side': 'original',
            'paragraphs': [
                {
                    'para_index': 0,
                    'text': "WHY ARE YOU TELLING THIS LIKE IT'S SOME KIND OF HORROR STORY?",
                    'items': [
                        {
                            'side': 'original',
                            'para_index': 0,
                            'item_index': 0,
                            'text': 'WHY ARE YOU TELLING THIS',
                            'box': {
                                'left': 0.20,
                                'top': 0.12,
                                'width': 0.60,
                                'height': 0.08,
                                'rotation_deg': 0.0,
                                'rotation_deg_css': 0.0,
                                'center': {'x': 0.50, 'y': 0.16},
                            },
                            'baseline_p1': {'x': 0.20, 'y': 0.16},
                            'baseline_p2': {'x': 0.80, 'y': 0.16},
                            'spans': [],
                        },
                        {
                            'side': 'original',
                            'para_index': 0,
                            'item_index': 1,
                            'text': "LIKE IT'S SOME KIND OF HORROR STORY?",
                            'box': {
                                'left': 0.22,
                                'top': 0.22,
                                'width': 0.56,
                                'height': 0.08,
                                'rotation_deg': 0.0,
                                'rotation_deg_css': 0.0,
                                'center': {'x': 0.50, 'y': 0.26},
                            },
                            'baseline_p1': {'x': 0.22, 'y': 0.26},
                            'baseline_p2': {'x': 0.78, 'y': 0.26},
                            'spans': [],
                        },
                    ],
                },
            ],
        }
        translated_tree = {
            'side': 'translated',
            'paragraphs': [
                {
                    'para_index': 0,
                    'text': 'Why tell it like a horror story?',
                    'items': [
                        {
                            'side': 'translated',
                            'para_index': 0,
                            'item_index': 0,
                            'text': 'Why tell it like a horror story?',
                            'box': {
                                'left': 0.35,
                                'top': 0.02,
                                'width': 0.18,
                                'height': 0.04,
                                'rotation_deg': 0.0,
                                'rotation_deg_css': 0.0,
                                'center': {'x': 0.44, 'y': 0.04},
                            },
                            'baseline_p1': {'x': 0.35, 'y': 0.04},
                            'baseline_p2': {'x': 0.53, 'y': 0.04},
                            'spans': [],
                        },
                    ],
                },
            ],
        }

        patched, meta = server._patch_text_onto_original_geometry(
            original_tree,
            translated_tree,
            '',
            'en',
            '',
            '',
            800,
            1200,
        )

        self.assertTrue(meta['patched'])
        self.assertIsNotNone(patched)
        para = patched['paragraphs'][0]
        self.assertEqual(para['side'], 'translated')
        self.assertIn('horror story', para['text'])
        self.assertEqual(len(para['items']), 2)
        self.assertAlmostEqual(para['items'][0]['box']['top'], 0.12)
        self.assertAlmostEqual(para['items'][1]['box']['top'], 0.22)

    def test_combined_erase_spans_uses_original_and_translated_boxes(self):
        original_tree = {
            'paragraphs': [
                {'items': [{'spans': [{
                    'text': 'WHY',
                    'box': {'left': 0.1, 'top': 0.1, 'width': 0.2, 'height': 0.05},
                }]}]},
            ],
        }
        translated_tree = {
            'paragraphs': [
                {'items': [{'spans': [{
                    'text': 'HORROR',
                    'box': {'left': 0.45, 'top': 0.1, 'width': 0.2, 'height': 0.05},
                }]}]},
            ],
        }

        spans = server._combined_erase_spans(original_tree, translated_tree)

        self.assertEqual(len(spans), 2)
        self.assertEqual([s['text'] for s in spans], ['WHY', 'HORROR'])

    def test_merge_split_paragraphs_at_tile_boundary(self):
        tree = {
            'side': 'original',
            'paragraphs': [
                {
                    'para_index': 0,
                    'text': 'WHY ARE YOU TELLING THIS',
                    'bounds_px': (200.0, 1000.0, 600.0, 1090.0),
                    'items': [
                        {
                            'side': 'original',
                            'para_index': 0,
                            'item_index': 0,
                            'text': 'WHY ARE YOU TELLING THIS',
                            'box': {'left': 0.25, 'top': 0.33, 'width': 0.5, 'height': 0.03, 'center': {'x': 0.5, 'y': 0.345}},
                            'spans': []
                        }
                    ]
                },
                {
                    'para_index': 1,
                    'text': 'TELLING THIS LIKE IT\'S SOME KIND OF HORROR STORY?',
                    'bounds_px': (202.0, 1010.0, 602.0, 1200.0),
                    'items': [
                        {
                            'side': 'original',
                            'para_index': 1,
                            'item_index': 0,
                            'text': 'TELLING THIS LIKE IT\'S SOME KIND OF HORROR STORY?',
                            'box': {'left': 0.25, 'top': 0.34, 'width': 0.5, 'height': 0.06, 'center': {'x': 0.5, 'y': 0.37}},
                            'spans': []
                        }
                    ]
                }
            ]
        }
        
        tile_ranges = [(0, 1100), (920, 1500)]
        meta = server._dedupe_tree_paragraphs(tree, 800, 3000, tile_ranges)
        
        self.assertEqual(meta['merged'], 1)
        self.assertEqual(len(tree['paragraphs']), 1)
        para = tree['paragraphs'][0]
        self.assertEqual(para['para_index'], 0)
        self.assertEqual(para['text'], "WHY ARE YOU TELLING THIS LIKE IT'S SOME KIND OF HORROR STORY?")
        self.assertEqual(len(para['items']), 2)
        self.assertEqual(para['items'][0]['text'], "WHY ARE YOU TELLING THIS")
        self.assertEqual(para['items'][1]['text'], "TELLING THIS LIKE IT'S SOME KIND OF HORROR STORY?")


if __name__ == '__main__':
    unittest.main()
