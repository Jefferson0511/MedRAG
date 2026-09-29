"""Split cleaned corpus Documents into chunks, each tagged with the page(s) it came from.

Two independent switches, so the Week 3 eval can measure each one:
- split_by_section: cut at FAQ/LactMed headings first, so a heading always travels with its answer
- add_header: prefix each chunk with "ORG | title | category | heading" so the embedding sees its context
Both off reproduces the plain RecursiveCharacterTextSplitter baseline.
"""
from bisect import bisect_right
from pathlib import Path
from statistics import median
from typing import NamedTuple

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from loader import load_corpus

# chunk_size and chunk_overlap count CHARACTERS (the splitter measures with len()), not tokens.
# 800 chars is roughly 150-200 tokens: under all-MiniLM-L6-v2's input limit, still a full FAQ answer.
# These are starting values; the eval run decides whether they change.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120

# Headingless sections shorter than this are title/metadata leftovers (e.g. "Ibuprofen / Revised / CASRN").
MIN_HEADINGLESS_SECTION_CHARS = 120

ORG_LABELS = {"acog": "ACOG", "cdc": "CDC", "lactmed": "LactMed"}

# LactMed records use a fixed set of section names; matched exactly, one per line.
LACTMED_HEADINGS = {
    "Drug Levels and Effects",
    "Summary of Use during Lactation",
    "Drug Levels",
    "Effects in Breastfed Infants",
    "Effects on Lactation and Breastmilk",
    "Alternate Drugs to Consider",
}

SENTENCE_ENDINGS = (".", "!", "?", ":", ";", ",", ")", "]")


class Marker(NamedTuple):
    """A heading found in the text, spanning lines [first_line, end_line)."""
    first_line: int
    end_line: int
    kind: str  # "question" (ACOG FAQ), "category" (ACOG topic group), or "section" (LactMed)
    label: str


class Section(NamedTuple):
    """One heading plus the body text under it, with the body's character offset in the document."""
    category: str | None
    heading: str | None
    body_start: int
    body: str


def find_section_markers(lines: list[str], org: str) -> list[Marker]:
    """Label heading lines. `lines` are the document's lines with line endings stripped."""
    markers: list[Marker] = []
    if org == "lactmed":
        for index, line in enumerate(lines):
            if line in LACTMED_HEADINGS:
                markers.append(Marker(index, index + 1, "section", line))
        return markers
    if org != "acog":
        return markers  # CDC pages have no reliably detectable headings; they get the header only

    # Pass 1: question headings. A heading can wrap onto two lines, e.g. the Q8 source heading
    # "What can be done ... in women with a" / "history of depression?". Join them when the line
    # above doesn't end a sentence AND is long: a line only wraps because it was full, which keeps
    # a short category label directly above a question from being glued onto it.
    questions: dict[int, Marker] = {}
    for index, line in enumerate(lines):
        if line.endswith("?") and len(line) <= 150:
            previous = lines[index - 1] if index > 0 else ""
            wrapped = len(previous) >= 60 and not previous.endswith(SENTENCE_ENDINGS)
            first = index - 1 if wrapped else index
            label = f"{previous} {line}" if wrapped else line
            questions[first] = Marker(first, index + 1, "question", label)

    # Pass 2: category headings, e.g. "Chronic Hypertension". Short, no end punctuation, starts with a
    # capital letter, and the next non-blank line starts a question. "Glossary" is a category by name.
    question_starts = set(questions)
    for index, line in enumerate(lines):
        if index in question_starts or any(m.first_line < index < m.end_line for m in questions.values()):
            continue
        looks_like_label = (
            line[:1].isupper() and len(line.split()) <= 6
            and not line.endswith(SENTENCE_ENDINGS) and "|" not in line
        )
        next_index = index + 1
        while next_index < len(lines) and not lines[next_index]:
            next_index += 1
        if line == "Glossary" or (looks_like_label and next_index in question_starts):
            markers.append(Marker(index, index + 1, "category", line))

    markers.extend(questions.values())
    return sorted(markers)


def split_sections(document: Document, split_by_section: bool) -> list[Section]:
    """Cut a joined Document into (category, heading, body) sections, keeping character offsets."""
    text = document.page_content
    if not split_by_section:
        return [Section(None, None, 0, text)]

    raw_lines = text.splitlines(keepends=True)  # keep "\n" so summed lengths give exact offsets
    line_offsets = [0]
    for raw_line in raw_lines:
        line_offsets.append(line_offsets[-1] + len(raw_line))
    markers = find_section_markers([raw_line.strip() for raw_line in raw_lines], document.metadata["org"])

    sections: list[Section] = []
    category: str | None = None
    heading: str | None = None
    body_first_line = 0
    for marker in markers + [Marker(len(raw_lines), len(raw_lines), "end", "")]:
        body_start, body_end = line_offsets[body_first_line], line_offsets[marker.first_line]
        sections.append(Section(category, heading, body_start, text[body_start:body_end]))
        if marker.kind == "category":
            category, heading = marker.label, None
        elif marker.kind in ("question", "section"):
            heading = marker.label
        body_first_line = marker.end_line
    return sections


def build_header(document: Document, section: Section) -> str:
    """'ACOG | Prenatal Care | How often should I ...?' style context line."""
    parts = [ORG_LABELS.get(document.metadata["org"], document.metadata["org"]), document.metadata["title"]]
    parts += [part for part in (section.category, section.heading) if part]
    return " | ".join(parts)


def page_for_offset(page_starts: list[int], offset: int) -> int:
    """Return the 1-based page number that contains the character at `offset`."""
    # counts how many pages start at or before offset, which is exactly the 1-based page number
    return bisect_right(page_starts, offset)


def chunk_documents(
    documents: list[Document],
    split_by_section: bool = True,
    add_header: bool = True,
    dropped: list[str] | None = None,
) -> list[Document]:
    """Split Documents into chunks with source, org, section, position, and page-range metadata.

    If `dropped` is given, the text of every discarded headingless stub is appended to it (for auditing).
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        add_start_index=True,  # records where each chunk begins, relative to the text it was given
    )
    chunks: list[Document] = []
    for document in documents:
        page_starts = document.metadata["page_starts"]
        chunk_index = 0
        for section in split_sections(document, split_by_section):
            if not section.body.strip():
                continue  # e.g. "Drug Levels and Effects" sits directly above "Summary of Use during Lactation"
            if split_by_section and not section.heading and not section.category \
                    and len(section.body.strip()) < MIN_HEADINGLESS_SECTION_CHARS:
                if dropped is not None:
                    dropped.append(f"{document.metadata['source']}: {section.body.strip()!r}")
                continue
            header = build_header(document, section) if add_header else ""
            for piece in splitter.create_documents([section.body]):
                start = section.body_start + piece.metadata["start_index"]  # absolute offset in the document
                end = start + len(piece.page_content) - 1  # last character, so cross-page chunks get a range
                chunks.append(
                    Document(
                        # the header is embedded with the body so retrieval sees the chunk's context
                        page_content=f"{header}\n\n{piece.page_content}" if header else piece.page_content,
                        metadata={
                            "source": document.metadata["source"],
                            "org": document.metadata["org"],
                            "title": document.metadata["title"],
                            "section_category": section.category,
                            "section_heading": section.heading,
                            "header": header,
                            "chunk_index": chunk_index,
                            "start_index": start,
                            "page_start": page_for_offset(page_starts, start),
                            "page_end": page_for_offset(page_starts, end),
                        },
                    )
                )
                chunk_index += 1
    return chunks


def chunk_body(chunk: Document) -> str:
    """The chunk's text without its header, i.e. the part that is an exact slice of the source document."""
    header = chunk.metadata["header"]
    return chunk.page_content[len(header) + 2:] if header else chunk.page_content


if __name__ == "__main__":
    documents = load_corpus(Path("data/raw"))
    text_by_source = {doc.metadata["source"]: doc.page_content for doc in documents}

    for split_by_section, add_header in [(False, False), (True, True)]:
        dropped: list[str] = []
        chunks = chunk_documents(documents, split_by_section, add_header, dropped)
        label = "section + header" if split_by_section else "simple (baseline)"

        # 1. Every chunk body must be an exact slice of its document at start_index, or page numbers are wrong.
        mismatches = 0
        for chunk in chunks:
            start, body = chunk.metadata["start_index"], chunk_body(chunk)
            if text_by_source[chunk.metadata["source"]][start : start + len(body)] != body:
                mismatches += 1
        body_lengths = [len(chunk_body(chunk)) for chunk in chunks]
        ends_with_question = sum(1 for chunk in chunks if chunk_body(chunk).rstrip().endswith("?"))
        print(f"=== {label}: {len(chunks)} chunks, {mismatches} start_index mismatches")
        print(f"    body length: min {min(body_lengths)}, median {median(body_lengths):.0f}, max {max(body_lengths)}")
        print(f"    chunks whose body ends in a question: {ends_with_question}")
        for stub in dropped:
            print(f"    dropped stub: {stub}")
        print()

    # 2. Audit the section markers that were detected, per document.
    for document in documents:
        sections = split_sections(document, split_by_section=True)
        labelled = [s for s in sections if s.heading or s.category]
        if labelled:
            print(f"--- {document.metadata['source']}: {len(labelled)} labelled sections")
            for section in labelled:
                print(f"      [{section.category or '-'}] {section.heading or '(category intro)'}")

    # 3. Spot-check the chunks that carry evidence for specific eval questions.
    for label, needle in [("Q4", "Before 10 weeks"), ("Q8", "If you have a history of depression"),
                          ("Q12", "Overwhelming tiredness")]:
        for chunk in chunks:
            if needle in chunk.page_content:
                meta = chunk.metadata
                print(f"\n===== {label} | {meta['source']} | chunk {meta['chunk_index']} "
                      f"| pages {meta['page_start']}-{meta['page_end']} | {len(chunk.page_content)} chars")
                print(chunk.page_content)
