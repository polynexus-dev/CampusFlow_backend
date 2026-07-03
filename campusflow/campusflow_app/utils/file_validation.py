"""
campusflow_app/utils/file_validation.py

Shared allow-list validation for user-uploaded attachments (assignments,
submissions, etc). Blocks executable/markup file types that could be used
for stored-XSS or served as active content, and caps upload size.
"""
import os

ALLOWED_ATTACHMENT_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.txt', '.csv', '.zip',
    '.png', '.jpg', '.jpeg',
}

MAX_ATTACHMENT_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


def validate_attachment(uploaded_file):
    """
    Returns an error message string if the uploaded file is not allowed,
    or None if it passes validation.
    """
    if uploaded_file is None:
        return None

    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        allowed = ', '.join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))
        return f"Unsupported file type '{ext}'. Allowed types: {allowed}."

    if uploaded_file.size > MAX_ATTACHMENT_SIZE_BYTES:
        return f"File too large. Maximum allowed size is {MAX_ATTACHMENT_SIZE_BYTES // (1024 * 1024)} MB."

    return None
