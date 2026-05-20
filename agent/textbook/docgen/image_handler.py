import os
from PIL import Image

class ImageHandler:
    @staticmethod
    def resize_image(input_path: str, output_path: str, max_width: int = 800, max_height: int = 600):
        with Image.open(input_path) as img:
            img.thumbnail((max_width, max_height))
            img.save(output_path)

    @staticmethod
    def get_image_dimensions(image_path: str):
        with Image.open(image_path) as img:
            return img.size

    @staticmethod
    def convert_format(input_path: str, output_path: str, format: str = "PNG"):
        with Image.open(input_path) as img:
            img.save(output_path, format=format)
