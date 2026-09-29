"""Load and clean corpus PDFs into LangChain Documents.

load_pdf returns one cleaned Document per page. load_corpus returns one Document per file
(pages joined, tail boilerplate cut), with page_starts metadata for mapping chunks back to pages.
"""
from pathlib import Path
import re

from langchain_core.documents import Document
from pypdf import PdfReader


def normalize_whitespace(text: str) -> str:
    """Tidy layout-mode output: collapse runs of spaces and limit blank lines to one."""
    # layout mode pads text with spaces to mimic column positions; collapse them
    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in text.splitlines()]
    # keep single blank lines (paragraph breaks) but collapse longer runs
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# Whole-line print artifacts that repeat on every page. Each pattern must match the entire line.
BOILERPLATE_LINE_PATTERNS = [
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2}, \d{1,2}:\d{2} [AP]M .*$"),  # browser print header (CDC, ACOG CHAP)
    re.compile(r"^https?://\S*?(?<!\d)\s*\d{1,2}/\d{1,2}$"),         # browser print footer: URL + "page/total" (space optional)
    re.compile(r"^\d+ Drugs and Lactation Database \(LactMed®\)$"),   # LactMed even-page footer
    re.compile(r"^[A-Z][a-z]+ \d{1,2}$"),                            # LactMed odd-page footer, e.g. "Ibuprofen 3"
]


def strip_boilerplate_lines(text: str) -> tuple[str, list[str]]:
    """Remove whole-line print artifacts. Returns the cleaned text and the removed lines, for auditing."""
    kept: list[str] = []
    removed: list[str] = []
    for line in text.splitlines():
        if any(pattern.match(line) for pattern in BOILERPLATE_LINE_PATTERNS):
            removed.append(line)
        else:
            kept.append(line)
    return "\n".join(kept).strip(), removed


# Once-per-document header junk, removed from page 1 only (before joining, so page_starts stay correct).
# Keyed by source folder, because a rule that is safe for one publisher can delete content from another.
PAGE_ONE_JUNK_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "acog": [
        re.compile(r"^From the American College of Obstetricians & Gynecologists$", re.MULTILINE),
        re.compile(r"^By reading this page you agree to ACOG.s Terms and Conditions\.\s*Read terms$", re.MULTILINE),
        re.compile(r"^FAQs( .*)?$", re.MULTILINE),  # "FAQs" or "FAQs Prenatal Care"; the title lives in metadata
        re.compile(r"^Frequently Asked Questions$", re.MULTILINE),
    ],
    "cdc": [
        re.compile(r"\A[^\n]*\n"),  # line 1 is the site-section label, e.g. "Folic Acid", "HEAR HER Campaign"
        re.compile(r"^[A-Z]{3,5}\.? \d{1,2}, \d{4}\s*(• ESPAÑOL)?$", re.MULTILINE),  # "MAY 15, 2024 • ESPAÑOL"
        re.compile(r"^For Everyone$", re.MULTILINE),
    ],
    "lactmed": [
        re.compile(r"\ANLM Citation:.*?\n\n", re.DOTALL),  # citation block, up to the first blank line
        re.compile(r"^Disclaimer: Information presented in this database.*?(?=\n\n|\Z)", re.MULTILINE | re.DOTALL),
        re.compile(r"^Attribution Statement: LactMed is a registered trademark.*$", re.MULTILINE),
    ],
}


def strip_page_one_junk(text: str, org: str) -> str:
    """Remove this publisher's once-per-document header junk from page 1."""
    for pattern in PAGE_ONE_JUNK_PATTERNS.get(org, []):
        text = pattern.sub("", text)
    # removals leave gaps; tidy the blank lines again
    return normalize_whitespace(text)


def document_title(reader: PdfReader, path: Path) -> str:
    """Human-readable title from the PDF metadata, e.g. 'Prenatal Care | ACOG' -> 'Prenatal Care'."""
    raw_title = reader.metadata.title if reader.metadata and reader.metadata.title else path.stem
    # browser-printed titles append " | Section | Site"; the first part is the page's own title
    return raw_title.split(" | ")[0].strip()


def load_pdf(path: Path) -> list[Document]:
    """Read one PDF and return one cleaned Document per page."""
    reader = PdfReader(path)
    org = path.parent.name  # the source folder: "acog", "cdc", or "lactmed"
    title = document_title(reader, path)
    documents: list[Document] = []
    for page_number, page in enumerate(reader.pages, start=1):
        # layout mode keeps FAQ headings next to their answers; default mode reorders them
        text = normalize_whitespace(page.extract_text(extraction_mode="layout") or "")
        text, _removed = strip_boilerplate_lines(text)
        if page_number == 1:
            text = strip_page_one_junk(text, org)
        documents.append(
            Document(
                page_content=text,
                metadata={"source": path.as_posix(), "org": org, "title": title, "page": page_number},
            )
        )
    return documents


def join_pages(pages: list[Document]) -> Document:
    """Join one file's page Documents into a single Document, remembering where each page starts."""
    texts: list[str] = []
    page_starts: list[int] = []
    offset = 0
    for page in pages:
        page_starts.append(offset)
        texts.append(page.page_content)
        offset += len(page.page_content) + 1  # +1 for the "\n" separator added by join below
    first = pages[0].metadata
    return Document(
        page_content="\n".join(texts),
        metadata={"source": first["source"], "org": first["org"], "title": first["title"], "page_starts": page_starts},
    )


# Once-per-document tail markers: everything from the first match to the end is boilerplate.
# Each marker was checked against the joined text of every file it applies to.
TAIL_CUT_PATTERNS = [
    re.compile(r"^If you have further questions, contact your ob-gyn\.$", re.MULTILINE),  # ACOG FAQs
    re.compile(r"^Access the Society for Maternal-Fetal Medicine statement", re.MULTILINE),  # ACOG CHAP: link line
    re.compile(r"^Please contact clinical@acog\.org", re.MULTILINE),                    # ACOG CHAP advisory
    re.compile(r"^SOURCES AND PAGE INFO$", re.MULTILINE),                                # CDC pages
    re.compile(r"^Hear personal stories of pregnancy-related complications", re.MULTILINE),  # CDC Hear Her: link list
    re.compile(r"^References$", re.MULTILINE),                                           # LactMed records
]


def cut_tail(text: str) -> str:
    """Cut everything from the earliest tail marker onward. Returns text unchanged if no marker matches."""
    cut_positions: list[int] = []
    for pattern in TAIL_CUT_PATTERNS:
        match = pattern.search(text)
        if match:
            cut_positions.append(match.start())
    if not cut_positions:
        return text
    return text[: min(cut_positions)].rstrip()


def load_corpus(root: Path) -> list[Document]:
    """Load every PDF under root (recursively), in a stable sorted order."""
    documents: list[Document] = []
    for pdf_path in sorted(root.rglob("*.pdf")):
        document = join_pages(load_pdf(pdf_path))
        document.page_content = cut_tail(document.page_content)
        documents.append(document)
    return documents


if __name__ == "__main__":
    docs = load_corpus(Path("data/raw"))
    print(f"{len(docs)} documents\n")
    for doc in docs:
        print("=" * 80)
        print(f"{doc.metadata['source']} | {doc.metadata['title']} | {len(doc.page_content)} chars")
        print(f"page_starts={doc.metadata['page_starts']}")
        print("--- HEAD ---")
        print(doc.page_content[:300])
        print("--- TAIL ---")
        print(doc.page_content[-250:])
