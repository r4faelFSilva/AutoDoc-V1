import io


def test_extract_txt(client, auth_headers):
    resp = client.post(
        "/api/agents/arquiteto/extract-spec",
        headers=auth_headers,
        files={"file": ("spec.txt", b"Sistema de pedidos com pagamentos PIX.", "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "PIX" in body["text"]
    assert body["truncated"] is False


def test_extract_docx(client, auth_headers):
    from docx import Document

    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph("Especificação do sistema de delivery.")
    doc.add_paragraph("Pico de 500 RPS no almoço.")
    doc.save(buf)

    resp = client.post(
        "/api/agents/arquiteto/extract-spec",
        headers=auth_headers,
        files={
            "file": (
                "spec.docx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert resp.status_code == 200, resp.text
    text = resp.json()["text"]
    assert "delivery" in text
    assert "500 RPS" in text


def test_extract_formato_nao_suportado(client, auth_headers):
    resp = client.post(
        "/api/agents/arquiteto/extract-spec",
        headers=auth_headers,
        files={"file": ("spec.exe", b"binario", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_extract_docx_corrompido(client, auth_headers):
    resp = client.post(
        "/api/agents/arquiteto/extract-spec",
        headers=auth_headers,
        files={"file": ("spec.docx", b"nao sou um docx", "application/zip")},
    )
    assert resp.status_code == 400
