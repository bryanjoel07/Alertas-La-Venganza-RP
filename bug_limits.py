"""One file policy shared by the report form, upload worker and evidence store."""
BYTES_PER_MB = 1_000_000
MAX_FILE_MB = 120
MAX_CLIP_BYTES = MAX_FILE_MB * BYTES_PER_MB
# A full selection of ten 120 MB originals must fit the shared evidence budget.
MAX_STORED_CLIP_BYTES = 1536 * 1024 * 1024
MAX_REPORT_FILES = 10
IMAGE_TYPES = {'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg',
    '.webp':'image/webp','.gif':'image/gif','.heic':'image/heic','.heif':'image/heif','.avif':'image/avif'}
VIDEO_TYPES = {'.mp4':'video/mp4','.m4v':'video/mp4','.mov':'video/quicktime','.webm':'video/webm'}
FILE_TYPES = {**IMAGE_TYPES, **VIDEO_TYPES}
