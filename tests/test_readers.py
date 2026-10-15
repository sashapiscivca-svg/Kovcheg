import pytest

from kovcheg.readers import SkipFile, decode_text, iter_zim, parse_html, read_file


def test_encoding_fallbacks(tmp_path):
    assert decode_text("привіт".encode()) == "привіт"
    assert decode_text("﻿hello".encode()) == "hello"
    assert decode_text("Київ".encode("cp1251")) == "Київ"
    assert decode_text(b"\x81\x98\xff") == "\x81\x98ÿ"          # 0x98 is undefined in cp1251 → latin-1
    p = tmp_path / "a.txt"
    p.write_bytes("Перша допомога".encode("cp1251"))
    doc = read_file(p)
    assert doc.text == "Перша допомога" and doc.kind == "text" and doc.title == "a"


def test_skip_reasons(tmp_path):
    (tmp_path / "x.exe").write_bytes(b"MZ\x00\x00")
    (tmp_path / "bin.txt").write_bytes(b"abc\x00def")
    (tmp_path / "empty.md").write_text("  \n")
    (tmp_path / "noext").write_bytes(b"\x00\x01")
    with pytest.raises(SkipFile, match="unsupported file type .exe"):
        read_file(tmp_path / "x.exe")
    with pytest.raises(SkipFile, match="binary"):
        read_file(tmp_path / "bin.txt")
    with pytest.raises(SkipFile, match="empty"):
        read_file(tmp_path / "empty.md")
    with pytest.raises(SkipFile, match="binary"):
        read_file(tmp_path / "noext")


def test_code_and_csv(tmp_path):
    (tmp_path / "s.py").write_text("def f():\n    return 1\n")
    (tmp_path / "t.csv").write_text("drug,dose\nparacetamol,500 mg\n")
    assert read_file(tmp_path / "s.py").kind == "code"
    assert "paracetamol,500 mg" in read_file(tmp_path / "t.csv").text


def test_html_boilerplate_and_sections():
    html = """<html><head><title>Guide &amp; more</title><style>.a{}</style></head><body>
    <nav><ul><li>Menu</li></ul></nav><div class="navbox">NAVBOX</div>
    <h1>Water</h1><p>Boil   water<br>for one minute.</p><script>alert('x')</script>
    <h2>Altitude<span class="mw-editsection">[edit]</span></h2><p>Boil three minutes.</p>
    <table><tr><th>Height</th><td>2000 m</td></tr></table><footer>Copyright</footer><img src=x><p>Last.</p></body></html>"""
    doc = parse_html(html, "f")
    assert doc.title == "Guide & more"
    t = doc.text
    for junk in ("Menu", "NAVBOX", "alert", "Copyright", "[edit]", ".a{}"):
        assert junk not in t
    secs = {s.heading: s.text for s in doc.sections}
    assert secs["Water"] == "Boil water\n\nfor one minute."
    assert "Boil three minutes." in secs["Altitude"] and "Height | 2000 m" in secs["Altitude"] and "Last." in secs["Altitude"]


def test_pdf_pages(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    w = pypdf.PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_ref = w._add_object(font)
    for text in ("Page one says J18.9 pneumonia.", "Page two covers burns."):
        page = w.add_blank_page(300, 200)
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = w._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})})
    w.add_metadata({"/Title": "Test manual"})
    p = tmp_path / "m.pdf"
    with open(p, "wb") as f:
        w.write(f)
    doc = read_file(p)
    assert doc.kind == "pdf" and doc.title == "Test manual"
    assert [s.page for s in doc.sections] == [1, 2]
    assert "J18.9" in doc.sections[0].text and "burns" in doc.sections[1].text

    blank = pypdf.PdfWriter()
    blank.add_blank_page(100, 100)
    with open(tmp_path / "scan.pdf", "wb") as f:
        blank.write(f)
    with pytest.raises(SkipFile, match="no extractable text"):
        read_file(tmp_path / "scan.pdf")


def test_docx_headings_and_tables(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Field manual", 0)
    d.add_paragraph("Intro paragraph.")
    d.add_heading("Bleeding", 1)
    d.add_paragraph("Press on the wound.")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Tourniquet", "2 hours max"
    d.add_heading("Burns", 1)
    d.add_paragraph("Cool with water.")
    p = tmp_path / "f.docx"
    d.save(p)
    doc = read_file(p)
    assert doc.title == "Field manual" and doc.kind == "docx"
    secs = {s.heading: s.text for s in doc.sections}
    assert secs["Field manual"] == "Intro paragraph."
    assert secs["Bleeding"] == "Press on the wound.\n\nTourniquet | 2 hours max"
    assert secs["Burns"] == "Cool with water."


def make_zim(path, articles):
    writer = pytest.importorskip("libzim.writer")

    class Item(writer.Item):
        def __init__(self, p, title, html, mime="text/html"):
            super().__init__()
            self.p, self.t, self.h, self.m = p, title, html, mime

        def get_path(self):
            return self.p

        def get_title(self):
            return self.t

        def get_mimetype(self):
            return self.m

        def get_contentprovider(self):
            return writer.StringProvider(self.h)

        def get_hints(self):
            return {writer.Hint.FRONT_ARTICLE: True}

    with writer.Creator(str(path)).config_indexing(False, "eng") as c:
        c.set_mainpath(articles[0][0])
        for a in articles:
            c.add_item(Item(*a))
        c.add_redirection("Redir", "Redirect", articles[0][0], {})
        for k, v in (("Title", "t"), ("Language", "eng"), ("Creator", "c"), ("Publisher", "p"), ("Description", "d"), ("Date", "2026-10-15"),
                     ("Name", "n")):
            c.add_metadata(k, v)


def test_zim_iterates_all_articles(tmp_path):
    p = tmp_path / "w.zim"
    arts = [(f"A{i}", f"Title {i}", f"<html><body><h1>Title {i}</h1><p>Article body {i} with ÿ Ж.</p><script>x</script></body></html>")
            for i in range(5)]
    arts.append(("style.css", "", "body{}", "text/css"))
    make_zim(p, arts)
    got = {a.path: a for a in iter_zim(p)}
    assert set(got) == {f"A{i}" for i in range(5)}
    doc = got["A3"].parse()
    assert doc.title == "Title 3" and doc.kind == "zim" and "Article body 3 with ÿ Ж." in doc.text and "x" not in doc.text.split()
