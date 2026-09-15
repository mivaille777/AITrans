from pathlib import Path

from backend.rag.parsers.html import HtmlDocumentParser


def test_html_parser_removes_noise_and_extracts_sections(tmp_path: Path) -> None:
    path = tmp_path / "paper.html"
    path.write_text(
        """
        <html>
          <head><title>RAG Paper</title><style>.x{}</style></head>
          <body>
            <nav>menu</nav>
            <h1>Intro</h1><p>Useful text.</p>
            <script>secret()</script>
            <h2>Methods</h2><p>PID and GP.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    result = HtmlDocumentParser().parse(path)

    assert result.document.title == "RAG Paper"
    assert "menu" not in result.text
    assert "secret" not in result.text
    assert [section.heading for section in result.sections] == ["Intro", "Methods"]
    assert "PID and GP." in result.sections[1].text
