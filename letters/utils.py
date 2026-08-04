import io
import os
from PIL import Image, ImageOps
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.exceptions import ValidationError

# Try importing pypdf for PDF compression
try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


def compress_attachment_file(uploaded_file, target_size_bytes=2 * 1024 * 1024):
    """
    Automatically compresses an uploaded image or PDF file if its size exceeds target_size_bytes (default 2 MB).
    Returns an InMemoryUploadedFile if compressed, or the original file if already within limits.
    Raises ValidationError if compression fails to bring file size below target_size_bytes.
    """
    if not uploaded_file or uploaded_file.size <= target_size_bytes:
        return uploaded_file

    filename = uploaded_file.name
    ext = os.path.splitext(filename)[1].lower()

    # ==========================================
    # 1. Image compression (.jpg, .jpeg, .png)
    # ==========================================
    if ext in ['.jpg', '.jpeg', '.png']:
        try:
            uploaded_file.seek(0)
            image = Image.open(uploaded_file)

            # Auto-orient EXIF metadata if present
            try:
                image = ImageOps.exif_transpose(image)
            except Exception:
                pass

            format_to_save = 'JPEG'
            content_type = 'image/jpeg'
            if image.mode in ('RGBA', 'P'):
                image = image.convert('RGB')

            quality = 85
            max_dimension = 2400

            while True:
                out_buffer = io.BytesIO()
                w, h = image.size

                if max(w, h) > max_dimension:
                    scale = max_dimension / float(max(w, h))
                    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
                    resized_img = image.resize((new_w, new_h), getattr(Image, 'Resampling', Image).LANCZOS)
                else:
                    resized_img = image

                resized_img.save(out_buffer, format=format_to_save, quality=quality, optimize=True)
                size = out_buffer.tell()

                if size <= target_size_bytes:
                    out_buffer.seek(0)
                    new_filename = os.path.splitext(filename)[0] + '.jpg' if ext != '.jpg' else filename
                    return InMemoryUploadedFile(
                        file=out_buffer,
                        field_name=None,
                        name=new_filename,
                        content_type=content_type,
                        size=size,
                        charset=None
                    )

                if quality > 40:
                    quality -= 15
                else:
                    max_dimension = int(max_dimension * 0.7)
                    quality = 70

                if max_dimension < 300:
                    break

        except Exception:
            pass

    # ==========================================
    # 2. PDF compression (.pdf)
    # ==========================================
    elif ext == '.pdf' and PYPDF_AVAILABLE:
        try:
            # Pass 1: Simple content stream compression
            uploaded_file.seek(0)
            reader = pypdf.PdfReader(uploaded_file)
            writer = pypdf.PdfWriter()

            for page in reader.pages:
                new_page = writer.add_page(page)
                try:
                    new_page.compress_content_streams()
                except Exception:
                    pass

            writer.compress_identical_objects()
            out_buffer = io.BytesIO()
            writer.write(out_buffer)
            size = out_buffer.tell()

            if size <= target_size_bytes:
                out_buffer.seek(0)
                return InMemoryUploadedFile(
                    file=out_buffer,
                    field_name=None,
                    name=filename,
                    content_type='application/pdf',
                    size=size,
                    charset=None
                )

            # Pass 2: Deep image re-compression & downscaling embedded PDF images
            for target_max_dim, img_quality in [(1400, 55), (900, 45), (600, 35)]:
                uploaded_file.seek(0)
                reader = pypdf.PdfReader(uploaded_file)
                writer = pypdf.PdfWriter()

                for page in reader.pages:
                    new_page = writer.add_page(page)
                    for img_obj in new_page.images:
                        try:
                            pil_img = img_obj.image
                            w, h = pil_img.size
                            if max(w, h) > target_max_dim or pil_img.mode in ('RGBA', 'P'):
                                scale = min(1.0, target_max_dim / float(max(w, h)))
                                new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
                                resized = pil_img.resize((new_w, new_h), getattr(Image, 'Resampling', Image).LANCZOS)
                                if resized.mode in ('RGBA', 'P'):
                                    resized = resized.convert('RGB')
                                img_obj.replace(resized, quality=img_quality)
                        except Exception:
                            pass
                    try:
                        new_page.compress_content_streams()
                    except Exception:
                        pass

                writer.compress_identical_objects()
                out_buffer = io.BytesIO()
                writer.write(out_buffer)
                size = out_buffer.tell()

                if size <= target_size_bytes:
                    out_buffer.seek(0)
                    return InMemoryUploadedFile(
                        file=out_buffer,
                        field_name=None,
                        name=filename,
                        content_type='application/pdf',
                        size=size,
                        charset=None
                    )

        except Exception:
            pass

    # ==========================================
    # 3. Fallback validation error
    # ==========================================
    orig_mb = uploaded_file.size / (1024 * 1024)
    raise ValidationError(
        f'File size ({orig_mb:.2f} MB) exceeds the 2 MB limit and could not be automatically reduced below 2 MB. Please compress or resize the file before uploading.'
    )
