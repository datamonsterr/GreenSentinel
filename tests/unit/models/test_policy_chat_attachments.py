"""Unit tests for PolicyChatRequest attachments and schema validation."""

import base64
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.models.schemas import ChatAttachment, PolicyChatRequest


def test_attachment_valid_png():
    raw = b"test-png-image-data"
    b64 = base64.b64encode(raw).decode("ascii")
    att = ChatAttachment(name="dashboard.png", media_type="image/png", data_base64=b64)
    assert att.name == "dashboard.png"
    assert att.media_type == "image/png"


def test_attachment_valid_jpeg_and_webp():
    raw = b"image-content"
    b64 = base64.b64encode(raw).decode("ascii")
    att1 = ChatAttachment(name="photo.jpg", media_type="image/jpeg", data_base64=b64)
    att2 = ChatAttachment(name="photo.webp", media_type="image/webp", data_base64=b64)
    assert att1.media_type == "image/jpeg"
    assert att2.media_type == "image/webp"


def test_attachment_rejects_non_image_mime():
    raw = b"pdf-content"
    b64 = base64.b64encode(raw).decode("ascii")
    with pytest.raises(ValidationError):
        ChatAttachment(name="doc.pdf", media_type="application/pdf", data_base64=b64)

    with pytest.raises(ValidationError):
        ChatAttachment(name="anim.gif", media_type="image/gif", data_base64=b64)


def test_attachment_rejects_invalid_base64():
    with pytest.raises(ValidationError):
        ChatAttachment(name="bad.png", media_type="image/png", data_base64="not-valid-base64!@#$")


def test_attachment_rejects_exceeding_4mb():
    # 4 MB is 4 * 1024 * 1024 = 4194304 bytes. 4194305 bytes exceeds the limit.
    oversized = b"x" * (4 * 1024 * 1024 + 1)
    b64 = base64.b64encode(oversized).decode("ascii")
    with pytest.raises(ValidationError):
        ChatAttachment(name="huge.png", media_type="image/png", data_base64=b64)


def test_policy_chat_request_with_attachments_max_3():
    raw = b"small"
    b64 = base64.b64encode(raw).decode("ascii")
    attachments = [{"name": f"img_{i}.png", "media_type": "image/png", "data_base64": b64} for i in range(3)]
    req = PolicyChatRequest(
        query="Kiểm tra ảnh",
        case_id=uuid4(),
        attachments=attachments,
    )
    assert len(req.attachments) == 3


def test_policy_chat_request_rejects_more_than_3_attachments():
    raw = b"small"
    b64 = base64.b64encode(raw).decode("ascii")
    attachments = [{"name": f"img_{i}.png", "media_type": "image/png", "data_base64": b64} for i in range(4)]
    with pytest.raises(ValidationError):
        PolicyChatRequest(
            query="Kiểm tra ảnh",
            case_id=uuid4(),
            attachments=attachments,
        )


def test_policy_chat_request_reset_context_backward_compat():
    req1 = PolicyChatRequest(query="Xin chào", case_id=uuid4())
    assert req1.reset_context is False

    req2 = PolicyChatRequest(query="Xin chào", case_id=uuid4(), reset_context=True)
    assert req2.reset_context is True
