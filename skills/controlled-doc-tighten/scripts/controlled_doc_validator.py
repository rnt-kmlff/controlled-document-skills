#!/usr/bin/env python3
"""Deterministic mechanical safeguards for controlled document tightening.

This tool proves that a manifest exactly describes source/candidate byte edits,
that the edits reverse in both directions, and that configured lexical and
structural invariants did not change. It does not prove semantic equivalence.
"""

import argparse
import base64
import difflib
import hashlib
import json
import os
import platform
import re
import sys
import tempfile
import traceback
from pathlib import Path


TOOL_NAME = "controlled_doc_validator"
VERSION = "1.0.0"
MANIFEST_SCHEMA = "controlled-doc-tighten.edit-manifest"
REPORT_SCHEMA = "controlled-doc-tighten.validation-report"
DIFF_ALGORITHM = "line-sequencematcher-char-hunks-v1"
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_EDITS = 10000
CHAR_REFINE_LIMIT = 256 * 1024
SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt"}
LIMITATIONS = [
    "This report does not prove semantic equivalence or factual correctness.",
    "Protected-token checks are lexical and incomplete; project-specific entities and terms require a custom protection file.",
    "Native documents, layout, spreadsheet formula semantics, OCR and embedded objects are outside v1 scope.",
]


class InputError(Exception):
    pass


class ManifestError(Exception):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def b64encode(data):
    return base64.b64encode(data).decode("ascii")


def b64decode(value, context):
    if not isinstance(value, str):
        raise ManifestError("{} data_b64 must be a string".format(context))
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise ManifestError("{} contains invalid base64".format(context)) from exc


def read_document(path_value):
    path = Path(path_value)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise InputError(
            "unsupported input type {}; v1 supports UTF-8 .txt, .md, and .markdown only".format(
                path.suffix or "(none)"
            )
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InputError("cannot read {}: {}".format(path, exc)) from exc
    if len(data) > MAX_INPUT_BYTES:
        raise InputError(
            "{} exceeds the {} byte v1 limit".format(path.name, MAX_INPUT_BYTES)
        )
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InputError("{} is not strict UTF-8".format(path.name)) from exc
    return {"path": path, "label": path.name, "data": data, "text": text}


def read_json(path_value, kind):
    path = Path(path_value)
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise InputError(
                "{} exceeds the {} byte JSON limit".format(path.name, MAX_JSON_BYTES)
            )
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError("cannot read {} {}: {}".format(kind, path, exc)) from exc
    try:
        return json.loads(raw.decode("utf-8", errors="strict")), raw
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError("{} is not valid UTF-8 JSON".format(path.name)) from exc


def json_bytes(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def preflight_outputs(paths, force):
    for path_value in paths:
        if not path_value:
            continue
        path = Path(path_value)
        if path.exists() and not force:
            raise InputError("refusing to overwrite existing output {}".format(path))
        if not path.parent.exists():
            raise InputError("output directory does not exist: {}".format(path.parent))


def paths_same(first, second):
    first_path = Path(first)
    second_path = Path(second)
    try:
        if first_path.exists() and second_path.exists():
            return os.path.samefile(str(first_path), str(second_path))
    except OSError:
        pass
    return first_path.resolve(strict=False) == second_path.resolve(strict=False)


def reject_output_aliases(outputs, protected_inputs):
    present_outputs = [path for path in outputs if path]
    for index, output in enumerate(present_outputs):
        for other in present_outputs[index + 1 :]:
            if paths_same(output, other):
                raise InputError("output paths must be distinct")
        for protected in protected_inputs:
            if protected and paths_same(output, protected):
                raise InputError("an output path must not alias an input path")


def write_bytes(path_value, data, force=False):
    path = Path(path_value)
    if not force:
        try:
            file_descriptor = os.open(
                str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(file_descriptor, "wb") as handle:
                handle.write(data)
            return
        except FileExistsError as exc:
            raise InputError("refusing to overwrite existing output {}".format(path)) from exc
        except OSError as exc:
            raise InputError("cannot write {}: {}".format(path, exc)) from exc

    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".{}.".format(path.name), dir=str(path.parent)
        )
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary_name, str(path))
    except OSError as exc:
        try:
            if "temporary_name" in locals() and os.path.exists(temporary_name):
                os.unlink(temporary_name)
        except OSError:
            pass
        raise InputError("cannot write {}: {}".format(path, exc)) from exc


def byte_offsets(text):
    offsets = [0]
    total = 0
    for character in text:
        total += len(character.encode("utf-8"))
        offsets.append(total)
    return offsets


def line_column(text, char_offset):
    line = text.count("\n", 0, char_offset) + 1
    previous_newline = text.rfind("\n", 0, char_offset)
    column = char_offset + 1 if previous_newline < 0 else char_offset - previous_newline
    return line, column


def side_record(text, data, char_start, char_end, offsets):
    start_byte = offsets[char_start]
    end_byte = offsets[char_end]
    fragment = data[start_byte:end_byte]
    line, column = line_column(text, char_start)
    return {
        "start_byte": start_byte,
        "end_byte": end_byte,
        "sha256": sha256(fragment),
        "data_b64": b64encode(fragment),
        "line": line,
        "column": column,
    }


def changed_char_spans(source_text, candidate_text):
    source_lines = source_text.splitlines(keepends=True)
    candidate_lines = candidate_text.splitlines(keepends=True)
    source_line_offsets = [0]
    candidate_line_offsets = [0]
    for line in source_lines:
        source_line_offsets.append(source_line_offsets[-1] + len(line))
    for line in candidate_lines:
        candidate_line_offsets.append(candidate_line_offsets[-1] + len(line))

    spans = []
    line_matcher = difflib.SequenceMatcher(
        None, source_lines, candidate_lines, autojunk=False
    )
    for tag, i1, i2, j1, j2 in line_matcher.get_opcodes():
        if tag == "equal":
            continue
        source_start = source_line_offsets[i1]
        source_end = source_line_offsets[i2]
        candidate_start = candidate_line_offsets[j1]
        candidate_end = candidate_line_offsets[j2]
        source_fragment = source_text[source_start:source_end]
        candidate_fragment = candidate_text[candidate_start:candidate_end]

        if len(source_fragment) + len(candidate_fragment) <= CHAR_REFINE_LIMIT:
            character_matcher = difflib.SequenceMatcher(
                None, source_fragment, candidate_fragment, autojunk=False
            )
            for char_tag, a1, a2, b1, b2 in character_matcher.get_opcodes():
                if char_tag != "equal":
                    spans.append(
                        (
                            source_start + a1,
                            source_start + a2,
                            candidate_start + b1,
                            candidate_start + b2,
                        )
                    )
        else:
            spans.append((source_start, source_end, candidate_start, candidate_end))

    coalesced = []
    for span in spans:
        if (
            coalesced
            and coalesced[-1][1] == span[0]
            and coalesced[-1][3] == span[2]
        ):
            previous = coalesced[-1]
            coalesced[-1] = (previous[0], span[1], previous[2], span[3])
        else:
            coalesced.append(span)
    return coalesced


def make_manifest_value(source, candidate):
    source_offsets = byte_offsets(source["text"])
    candidate_offsets = byte_offsets(candidate["text"])
    edits = []
    for number, span in enumerate(
        changed_char_spans(source["text"], candidate["text"]), start=1
    ):
        source_start, source_end, candidate_start, candidate_end = span
        source_side = side_record(
            source["text"], source["data"], source_start, source_end, source_offsets
        )
        candidate_side = side_record(
            candidate["text"],
            candidate["data"],
            candidate_start,
            candidate_end,
            candidate_offsets,
        )
        if source_start == source_end:
            operation = "insert"
        elif candidate_start == candidate_end:
            operation = "delete"
        else:
            operation = "replace"
        edits.append(
            {
                "id": "E{:06d}".format(number),
                "op": operation,
                "source": source_side,
                "candidate": candidate_side,
                "annotation": None,
            }
        )

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "schema_version": 1,
        "tool": {
            "name": TOOL_NAME,
            "version": VERSION,
            "diff_algorithm": DIFF_ALGORITHM,
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
        },
        "encoding": "utf-8",
        "source": {
            "label": source["label"],
            "sha256": sha256(source["data"]),
            "size_bytes": len(source["data"]),
        },
        "candidate": {
            "label": candidate["label"],
            "sha256": sha256(candidate["data"]),
            "size_bytes": len(candidate["data"]),
        },
        "edits": edits,
    }
    verify_manifest(manifest, source["data"], candidate["data"])
    return manifest


def require_int(record, key, context):
    value = record.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ManifestError("{} {} must be a non-negative integer".format(context, key))
    return value


def require_positive_int(record, key, context):
    value = require_int(record, key, context)
    if value == 0:
        raise ManifestError("{} {} must be positive".format(context, key))
    return value


def expected_line_columns(data, requested_offsets):
    requested = set(requested_offsets)
    positions = {}
    byte_offset = 0
    line = 1
    column = 1
    text = data.decode("utf-8", errors="strict")
    if 0 in requested:
        positions[0] = (line, column)
    for character in text:
        byte_offset += len(character.encode("utf-8"))
        if character == "\n":
            line += 1
            column = 1
        else:
            column += 1
        if byte_offset in requested:
            positions[byte_offset] = (line, column)
    if set(positions) != requested:
        raise ManifestError("an edit offset is out of bounds or splits a UTF-8 character")
    return positions


def verified_edits(manifest, source_data=None, candidate_data=None):
    if not isinstance(manifest, dict):
        raise ManifestError("manifest must be a JSON object")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("schema_version") != 1:
        raise ManifestError("unsupported manifest schema")
    if manifest.get("encoding") != "utf-8":
        raise ManifestError("unsupported manifest encoding")
    edits = manifest.get("edits")
    if not isinstance(edits, list):
        raise ManifestError("manifest edits must be a list")
    if len(edits) > MAX_EDITS:
        raise ManifestError("manifest exceeds the {} edit limit".format(MAX_EDITS))
    source_record = manifest.get("source")
    candidate_record = manifest.get("candidate")
    if not isinstance(source_record, dict) or not isinstance(candidate_record, dict):
        raise ManifestError("manifest file metadata is missing")
    source_size = require_int(source_record, "size_bytes", "manifest source")
    candidate_size = require_int(candidate_record, "size_bytes", "manifest candidate")
    if not isinstance(source_record.get("sha256"), str) or not isinstance(
        candidate_record.get("sha256"), str
    ):
        raise ManifestError("manifest whole-file hashes are missing")

    normalized = []
    previous_source_end = 0
    previous_candidate_end = 0
    identifiers = set()
    for index, edit in enumerate(edits, start=1):
        context = "edit {}".format(index)
        if not isinstance(edit, dict):
            raise ManifestError("{} must be an object".format(context))
        identifier = edit.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ManifestError("{} has an invalid id".format(context))
        if identifier in identifiers:
            raise ManifestError("duplicate edit id {}".format(identifier))
        identifiers.add(identifier)
        source = edit.get("source")
        candidate = edit.get("candidate")
        if not isinstance(source, dict) or not isinstance(candidate, dict):
            raise ManifestError("{} sides must be objects".format(identifier))

        source_start = require_int(source, "start_byte", identifier + " source")
        source_end = require_int(source, "end_byte", identifier + " source")
        candidate_start = require_int(candidate, "start_byte", identifier + " candidate")
        candidate_end = require_int(candidate, "end_byte", identifier + " candidate")
        source_line = require_positive_int(source, "line", identifier + " source")
        source_column = require_positive_int(source, "column", identifier + " source")
        candidate_line = require_positive_int(
            candidate, "line", identifier + " candidate"
        )
        candidate_column = require_positive_int(
            candidate, "column", identifier + " candidate"
        )
        if source_end < source_start or candidate_end < candidate_start:
            raise ManifestError("{} has a reversed span".format(identifier))
        if source_end > source_size or candidate_end > candidate_size:
            raise ManifestError("{} span exceeds a declared file size".format(identifier))
        if source_start < previous_source_end or candidate_start < previous_candidate_end:
            raise ManifestError("{} overlaps or is out of order".format(identifier))

        source_fragment = b64decode(source.get("data_b64"), identifier + " source")
        candidate_fragment = b64decode(
            candidate.get("data_b64"), identifier + " candidate"
        )
        if not source_fragment and not candidate_fragment:
            raise ManifestError("{} is an empty no-op edit".format(identifier))
        if len(source_fragment) != source_end - source_start:
            raise ManifestError("{} source fragment length mismatch".format(identifier))
        if len(candidate_fragment) != candidate_end - candidate_start:
            raise ManifestError("{} candidate fragment length mismatch".format(identifier))
        if sha256(source_fragment) != source.get("sha256"):
            raise ManifestError("{} source fragment hash mismatch".format(identifier))
        if sha256(candidate_fragment) != candidate.get("sha256"):
            raise ManifestError("{} candidate fragment hash mismatch".format(identifier))
        if source_data is not None:
            if source_end > len(source_data) or source_data[source_start:source_end] != source_fragment:
                raise ManifestError("{} does not match source bytes".format(identifier))
        if candidate_data is not None:
            if (
                candidate_end > len(candidate_data)
                or candidate_data[candidate_start:candidate_end] != candidate_fragment
            ):
                raise ManifestError("{} does not match candidate bytes".format(identifier))

        expected_op = (
            "insert"
            if not source_fragment
            else "delete"
            if not candidate_fragment
            else "replace"
        )
        if edit.get("op") != expected_op:
            raise ManifestError("{} operation does not match its spans".format(identifier))

        normalized.append(
            {
                "id": identifier,
                "op": expected_op,
                "source_start": source_start,
                "source_end": source_end,
                "candidate_start": candidate_start,
                "candidate_end": candidate_end,
                "source_fragment": source_fragment,
                "candidate_fragment": candidate_fragment,
                "annotation": edit.get("annotation"),
                "source_line": source_line,
                "source_column": source_column,
                "candidate_line": candidate_line,
                "candidate_column": candidate_column,
            }
        )
        previous_source_end = source_end
        previous_candidate_end = candidate_end
    if source_data is not None:
        positions = expected_line_columns(
            source_data, [edit["source_start"] for edit in normalized]
        )
        for edit in normalized:
            if positions[edit["source_start"]] != (
                edit["source_line"],
                edit["source_column"],
            ):
                raise ManifestError("{} has incorrect source coordinates".format(edit["id"]))
    if candidate_data is not None:
        positions = expected_line_columns(
            candidate_data, [edit["candidate_start"] for edit in normalized]
        )
        for edit in normalized:
            if positions[edit["candidate_start"]] != (
                edit["candidate_line"],
                edit["candidate_column"],
            ):
                raise ManifestError(
                    "{} has incorrect candidate coordinates".format(edit["id"])
                )
    return normalized


def reconstruct(data, edits, direction):
    output = bytearray()
    cursor = 0
    if direction == "forward":
        for edit in edits:
            output.extend(data[cursor : edit["source_start"]])
            output.extend(edit["candidate_fragment"])
            cursor = edit["source_end"]
    else:
        for edit in edits:
            output.extend(data[cursor : edit["candidate_start"]])
            output.extend(edit["source_fragment"])
            cursor = edit["candidate_end"]
    output.extend(data[cursor:])
    return bytes(output)


def verify_file_metadata(manifest, source_data=None, candidate_data=None):
    if not isinstance(manifest, dict):
        raise ManifestError("manifest must be a JSON object")
    for side_name, data in (("source", source_data), ("candidate", candidate_data)):
        record = manifest.get(side_name)
        if not isinstance(record, dict):
            raise ManifestError("manifest {} metadata is missing".format(side_name))
        if data is None:
            continue
        if record.get("sha256") != sha256(data):
            raise ManifestError("{} whole-file hash mismatch".format(side_name))
        if record.get("size_bytes") != len(data):
            raise ManifestError("{} whole-file size mismatch".format(side_name))


def verify_manifest(manifest, source_data, candidate_data):
    verify_file_metadata(manifest, source_data, candidate_data)
    edits = verified_edits(manifest, source_data, candidate_data)
    rebuilt_candidate = reconstruct(source_data, edits, "forward")
    rebuilt_source = reconstruct(candidate_data, edits, "reverse")
    if rebuilt_candidate != candidate_data:
        raise ManifestError("source-to-candidate reconstruction mismatch")
    if rebuilt_source != source_data:
        raise ManifestError("candidate-to-source reconstruction mismatch")
    return edits


def document_metrics(document):
    text = document["text"]
    return {
        "bytes": len(document["data"]),
        "codepoints": len(text),
        "lines": 0 if not text else len(text.splitlines()),
        "whitespace_words": len(re.findall(r"\S+", text, flags=re.UNICODE)),
    }


def overlap(edit_start, edit_end, protected_start, protected_end):
    if protected_start == protected_end:
        return edit_start == protected_start and edit_end == protected_end
    if edit_start == edit_end:
        return protected_start < edit_start < protected_end
    return edit_start < protected_end and protected_start < edit_end


def regex_items(text, data, pattern, flags=0, group=0):
    offsets = byte_offsets(text)
    items = []
    for match in re.finditer(pattern, text, flags):
        start, end = match.span(group)
        start_byte, end_byte = offsets[start], offsets[end]
        items.append(
            {
                "value": data[start_byte:end_byte],
                "start": start_byte,
                "end": end_byte,
                "line": line_column(text, start)[0],
                "column": line_column(text, start)[1],
            }
        )
    return items


def block_items(text, data, predicate):
    offsets = byte_offsets(text)
    items = []
    char_cursor = 0
    block_start = None
    block_end = None
    for line in text.splitlines(keepends=True):
        if predicate(line):
            if block_start is None:
                block_start = char_cursor
            block_end = char_cursor + len(line)
        elif block_start is not None:
            start_byte, end_byte = offsets[block_start], offsets[block_end]
            items.append(
                {
                    "value": data[start_byte:end_byte],
                    "start": start_byte,
                    "end": end_byte,
                    "line": line_column(text, block_start)[0],
                    "column": 1,
                }
            )
            block_start = None
            block_end = None
        char_cursor += len(line)
    if block_start is not None:
        start_byte, end_byte = offsets[block_start], offsets[block_end]
        items.append(
            {
                "value": data[start_byte:end_byte],
                "start": start_byte,
                "end": end_byte,
                "line": line_column(text, block_start)[0],
                "column": 1,
            }
        )
    return items


def fenced_code_items(text, data):
    offsets = byte_offsets(text)
    lines = text.splitlines(keepends=True)
    line_offsets = [0]
    for line in lines:
        line_offsets.append(line_offsets[-1] + len(line))
    items = []
    index = 0
    while index < len(lines):
        opening = re.match(r"^[ \t]*((?:\x60{3,})|(?:~{3,}))", lines[index])
        if not opening:
            index += 1
            continue
        marker = opening.group(1)
        closing_pattern = re.compile(
            r"^[ \t]*" + re.escape(marker[0]) + r"{" + str(len(marker)) + r",}[ \t]*(?:\r?\n)?$"
        )
        end_index = index + 1
        while end_index < len(lines) and not closing_pattern.match(lines[end_index]):
            end_index += 1
        if end_index < len(lines):
            end_index += 1
        else:
            end_index = len(lines)
        start_char = line_offsets[index]
        end_char = line_offsets[end_index]
        start_byte, end_byte = offsets[start_char], offsets[end_char]
        line, column = line_column(text, start_char)
        items.append(
            {
                "value": data[start_byte:end_byte],
                "start": start_byte,
                "end": end_byte,
                "line": line,
                "column": column,
            }
        )
        index = end_index
    return items


def yaml_frontmatter_items(text, data):
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return []
    end_char = len(lines[0])
    for line in lines[1:]:
        end_char += len(line)
        if line.rstrip("\r\n") in {"---", "..."}:
            break
    offsets = byte_offsets(text)
    end_byte = offsets[end_char]
    return [
        {
            "value": data[:end_byte],
            "start": 0,
            "end": end_byte,
            "line": 1,
            "column": 1,
        }
    ]


def code_math_items(text, data):
    patterns = [
        r"(?s)\x60[^\x60\n]+\x60",
        r"(?s)\$\$.*?\$\$",
        r"(?<!\$)\$(?!\$)(?:\\.|[^\n$])+\$(?!\$)",
    ]
    items = fenced_code_items(text, data)
    items.extend(yaml_frontmatter_items(text, data))
    items.extend(
        regex_items(
            text,
            data,
            r"(?m)^[ \t]*=[A-Za-z][^\r\n]*$",
        )
    )
    for pattern in patterns:
        items.extend(regex_items(text, data, pattern))
    return sorted(items, key=lambda item: (item["start"], item["end"]))


def table_items(text, data):
    lines = text.splitlines(keepends=True)
    marked = [False] * len(lines)
    for index, line in enumerate(lines):
        if line.lstrip().startswith("|") or (
            line.count("|") >= 2 and not line.lstrip().startswith("#")
        ):
            marked[index] = True

    def cells(line):
        value = line.rstrip("\r\n").strip()
        if value.startswith("|"):
            value = value[1:]
        if value.endswith("|"):
            value = value[:-1]
        return [cell.strip() for cell in value.split("|")]

    def delimiter(line):
        values = cells(line)
        return len(values) >= 2 and all(
            re.fullmatch(r":?-{3,}:?", value) is not None for value in values
        )

    for index, line in enumerate(lines):
        if index == 0 or "|" not in line or not delimiter(line):
            continue
        marked[index - 1] = True
        marked[index] = True
        following = index + 1
        while following < len(lines) and "|" in lines[following]:
            marked[following] = True
            following += 1

    offsets = byte_offsets(text)
    line_offsets = [0]
    for line in lines:
        line_offsets.append(line_offsets[-1] + len(line))
    items = []
    index = 0
    while index < len(lines):
        if not marked[index]:
            index += 1
            continue
        start_index = index
        while index < len(lines) and marked[index]:
            index += 1
        start_char = line_offsets[start_index]
        end_char = line_offsets[index]
        start_byte, end_byte = offsets[start_char], offsets[end_char]
        line, column = line_column(text, start_char)
        items.append(
            {
                "value": data[start_byte:end_byte],
                "start": start_byte,
                "end": end_byte,
                "line": line,
                "column": column,
            }
        )
    return items


PROTECTED_PATTERNS = [
    (
        "PROT_NUMERIC",
        r"(?<![\w])(?:(?:\(\s*(?:\d{1,3}(?:[,_ ]\d{3})+|\d+)(?:\.\d+)?\s*\))|(?:[+\-−]?(?:\d{1,3}(?:[,_ ]\d{3})+|\d+)(?:\.\d+)?))(?:\s*(?:-|–|—|to)\s*[+\-−]?(?:\d{1,3}(?:[,_ ]\d{3})+|\d+)(?:\.\d+)?)?(?:\s*(?:%|bp|bps|basis points?|[kmgt]n|million|billion|thousand|kg|g|t|tonnes?|tons?|km|m|cm|mm|l|ml|MW|MWh|kW|kWh|days?|business\s+days?|weeks?|months?|years?))?(?![\w])",
        re.IGNORECASE,
    ),
    (
        "PROT_CURRENCY_AMOUNT",
        r"(?<!\w)(?:(?:USD|EUR|GBP|AED|ZAR|JPY|CNY|RMB|CHF|CAD|AUD)|[$€£¥])\s*(?:(?:\(\s*(?:\d{1,3}(?:[,_ ]\d{3})+|\d+)(?:\.\d+)?\s*\))|(?:[+\-−]?(?:\d{1,3}(?:[,_ ]\d{3})+|\d+)(?:\.\d+)?))(?:\s*(?:k|m|mn|million|bn|billion))?(?!\w)",
        re.IGNORECASE,
    ),
    (
        "PROT_DATE_TIME",
        r"(?<!\w)(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Sept(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Sept(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}|\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)(?!\w)",
        re.IGNORECASE,
    ),
    (
        "PROT_MODAL_NEGATION",
        r"\b(?:shall|must|may|should|will|can|could|would|not|no|never|cannot|can't|won't|mustn't|shalln't)\b",
        re.IGNORECASE,
    ),
    (
        "PROT_CONDITION_QUALIFIER",
        r"\b(?:if|unless|except|subject\s+to|provided\s+that|only\s+if|only|until|before|after|within|at\s+least|not\s+less\s+than|up\s+to|approximately|roughly|estimated|expected|currently|historically|unaudited|appears?|seems?|assuming|pending|unverified|without(?:\s+recourse)?|with\s+recourse|including|excluding|to\s+our\s+knowledge|to\s+be\s+confirmed)\b",
        re.IGNORECASE,
    ),
    (
        "PROT_DEFINED_TERM",
        r"(?:\b[A-Z][A-Z0-9_-]{1,}\b|[\"“][^\"”\n]{1,80}[\"”]\s+(?:means|shall\s+mean|has\s+the\s+meaning))",
        0,
    ),
    (
        "PROT_CLAUSE_REFERENCE",
        r"\b(?:clause|section|schedule|annex|appendix|exhibit)\s+[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*(?:\([A-Za-z0-9ivxIVX]+\))*",
        re.IGNORECASE,
    ),
    (
        "PROT_CITATION_LINK",
        r"(?:\[[^\]\n]+\]\([^\)\n]+\)|https?://[^\s)>]+|\[\^[^\]\n]+\]|^\[\^[^\]\n]+\]:[^\n]*|\[(?:\d+|[A-Za-z]+\d{4}[a-z]?)\])",
        re.MULTILINE,
    ),
    (
        "PROT_QUOTATION",
        r"(?:\"(?:\\.|[^\"\\\n])+\"|“[^”\n]+”)",
        0,
    ),
]


def protected_result(check_id, source_items, candidate_items, edits, include_snippets):
    source_values = [item["value"] for item in source_items]
    candidate_values = [item["value"] for item in candidate_items]
    sequence_equal = source_values == candidate_values
    overlaps = []
    for edit in edits:
        for item in source_items:
            if overlap(
                edit["source_start"],
                edit["source_end"],
                item["start"],
                item["end"],
            ):
                overlaps.append((edit["id"], "source", item))
        for item in candidate_items:
            if overlap(
                edit["candidate_start"],
                edit["candidate_end"],
                item["start"],
                item["end"],
            ):
                overlaps.append((edit["id"], "candidate", item))

    passed = sequence_equal and not overlaps
    findings = []
    if not sequence_equal:
        findings.append(
            {
                "rule_id": check_id,
                "summary": "Protected occurrence sequence changed.",
                "source_count": len(source_items),
                "candidate_count": len(candidate_items),
                "source_sequence_sha256": sha256(b"\x00".join(source_values)),
                "candidate_sequence_sha256": sha256(b"\x00".join(candidate_values)),
            }
        )
    for identifier, side, item in overlaps[:20]:
        finding = {
            "rule_id": check_id,
            "summary": "Edit {} overlaps a protected {} span.".format(identifier, side),
            "edit_id": identifier,
            "side": side,
            "line": item["line"],
            "column": item["column"],
            "span_sha256": sha256(item["value"]),
        }
        if include_snippets:
            finding["snippet"] = item["value"].decode(
                "utf-8", errors="replace"
            )[:80]
        findings.append(finding)
    return (
        {
            "id": check_id,
            "status": "pass" if passed else "fail",
            "severity": "blocking",
            "summary": (
                "{} protected occurrence(s) preserved without edit overlap.".format(
                    len(source_items)
                )
                if passed
                else "Protected content changed or was edited."
            ),
        },
        findings,
    )


def heading_items(document):
    items = regex_items(
        document["text"], document["data"], r"(?m)^#{1,6}[ \t]+[^\n\r]+"
    )
    items.extend(
        regex_items(
            document["text"],
            document["data"],
            r"(?m)^[^\r\n]+\r?\n(?:=+|-+)[ \t]*(?:\r?\n|$)",
        )
    )
    return sorted(items, key=lambda item: (item["start"], item["end"]))


def list_topology(text):
    result = []
    for line in text.splitlines():
        match = re.match(r"^([ \t]*)([-+*]|\d+[.)])[ \t]+", line)
        if match:
            result.append((match.group(1), re.sub(r"\d+", "#", match.group(2))))
    return result


def custom_items(document, protection):
    groups = []
    text = document["text"]
    data = document["data"]
    for literal in protection.get("literals", []):
        if not isinstance(literal, dict) or not isinstance(literal.get("id"), str):
            raise InputError("custom literal entries require an id")
        value = literal.get("text")
        if not isinstance(value, str) or not value:
            raise InputError("custom literal {} requires non-empty text".format(literal["id"]))
        flags = 0 if literal.get("case_sensitive", True) else re.IGNORECASE
        groups.append(
            (
                "literal." + literal["id"],
                regex_items(text, data, re.escape(value), flags),
            )
        )
    allowed_flags = {"IGNORECASE": re.IGNORECASE, "MULTILINE": re.MULTILINE}
    for regex_entry in protection.get("regexes", []):
        if not isinstance(regex_entry, dict) or not isinstance(regex_entry.get("id"), str):
            raise InputError("custom regex entries require an id")
        pattern = regex_entry.get("pattern")
        flags_value = 0
        if not isinstance(pattern, str) or not pattern:
            raise InputError("custom regex {} requires a pattern".format(regex_entry["id"]))
        flags_list = regex_entry.get("flags", [])
        if not isinstance(flags_list, list) or any(flag not in allowed_flags for flag in flags_list):
            raise InputError("custom regex {} uses unsupported flags".format(regex_entry["id"]))
        for flag in flags_list:
            flags_value |= allowed_flags[flag]
        try:
            matches = regex_items(text, data, pattern, flags_value)
            if any(item["start"] == item["end"] for item in matches):
                raise InputError(
                    "custom regex {} produces an empty match".format(regex_entry["id"])
                )
            groups.append(
                (
                    "regex." + regex_entry["id"],
                    matches,
                )
            )
        except re.error as exc:
            raise InputError("invalid custom regex {}: {}".format(regex_entry["id"], exc)) from exc
    offsets = byte_offsets(text)
    for region in protection.get("regions", []):
        if not isinstance(region, dict) or not isinstance(region.get("id"), str):
            raise InputError("custom region entries require an id")
        start_marker = region.get("start_marker")
        end_marker = region.get("end_marker")
        if (
            not isinstance(start_marker, str)
            or not isinstance(end_marker, str)
            or not start_marker
            or not end_marker
            or start_marker == end_marker
        ):
            raise InputError("custom region {} requires markers".format(region["id"]))
        items = []
        cursor = 0
        while True:
            start = text.find(start_marker, cursor)
            stray_end = text.find(end_marker, cursor)
            if stray_end >= 0 and (start < 0 or stray_end < start):
                raise InputError(
                    "custom region {} has an unmatched end marker".format(region["id"])
                )
            if start < 0:
                break
            end_marker_start = text.find(end_marker, start + len(start_marker))
            if end_marker_start < 0:
                raise InputError(
                    "custom region {} has an unmatched start marker".format(region["id"])
                )
            nested = text.find(start_marker, start + len(start_marker), end_marker_start)
            if nested >= 0:
                raise InputError("custom region {} is nested".format(region["id"]))
            end = end_marker_start + len(end_marker)
            start_byte, end_byte = offsets[start], offsets[end]
            line, column = line_column(text, start)
            items.append(
                {
                    "value": data[start_byte:end_byte],
                    "start": start_byte,
                    "end": end_byte,
                    "line": line,
                    "column": column,
                }
            )
            cursor = end
        if text.find(end_marker, cursor) >= 0:
            raise InputError(
                "custom region {} has an unmatched end marker".format(region["id"])
            )
        groups.append(("region." + region["id"], items))
    return groups


def load_protection(path_value):
    if not path_value:
        return None, None
    protection, raw = read_json(path_value, "protection file")
    if not isinstance(protection, dict) or protection.get("schema_version") != 1:
        raise InputError("unsupported custom protection schema")
    for key in ("literals", "regexes", "regions"):
        if key in protection and not isinstance(protection[key], list):
            raise InputError("custom protection {} must be a list".format(key))
    identifiers = set()
    for key in ("literals", "regexes", "regions"):
        for entry in protection.get(key, []):
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                raise InputError("custom protection entries require string ids")
            identifier = entry["id"]
            if not identifier or identifier in identifiers:
                raise InputError("custom protection ids must be non-empty and unique")
            identifiers.add(identifier)
    return protection, sha256(raw)


def annotation_check(edits, required):
    allowed_categories = {
        "filler",
        "empty-transition",
        "verbose-phrasing",
        "punctuation",
        "formatting",
        "exact-restatement",
        "other",
    }
    allowed_decisions = {"automatic", "author-approved", "unresolved"}
    findings = []
    for edit in edits:
        annotation = edit["annotation"]
        if not isinstance(annotation, dict):
            findings.append(
                {
                    "rule_id": "AUDIT_ANNOTATIONS",
                    "edit_id": edit["id"],
                    "summary": "Edit annotation is missing.",
                }
            )
            continue
        category = annotation.get("category")
        decision = annotation.get("decision")
        rationale = annotation.get("rationale")
        if category not in allowed_categories:
            findings.append(
                {
                    "rule_id": "AUDIT_ANNOTATIONS",
                    "edit_id": edit["id"],
                    "summary": "Edit category is missing or invalid.",
                }
            )
        if decision not in allowed_decisions or decision == "unresolved":
            findings.append(
                {
                    "rule_id": "AUDIT_ANNOTATIONS",
                    "edit_id": edit["id"],
                    "summary": "Edit decision is missing, invalid, or unresolved.",
                }
            )
        if not isinstance(rationale, str) or not rationale.strip():
            findings.append(
                {
                    "rule_id": "AUDIT_ANNOTATIONS",
                    "edit_id": edit["id"],
                    "summary": "Edit rationale is missing.",
                }
            )
        reviewer = annotation.get("reviewer")
        if decision == "author-approved" and (
            not isinstance(reviewer, str) or not reviewer.strip()
        ):
            findings.append(
                {
                    "rule_id": "AUDIT_ANNOTATIONS",
                    "edit_id": edit["id"],
                    "summary": "Author-approved edits require a named reviewer.",
                }
            )
        if (
            edit["op"] == "insert" or category in {"exact-restatement", "other"}
        ) and decision != "author-approved":
            findings.append(
                {
                    "rule_id": "AUDIT_ANNOTATIONS",
                    "edit_id": edit["id"],
                    "summary": "Insertions, exact restatements, and other edits require author approval.",
                }
            )
    if findings:
        return (
            {
                "id": "AUDIT_ANNOTATIONS",
                "status": "fail" if required else "warning",
                "severity": "blocking" if required else "warning",
                "summary": "{} edit annotation issue(s).".format(len(findings)),
            },
            findings,
        )
    return (
        {
            "id": "AUDIT_ANNOTATIONS",
            "status": "pass",
            "severity": "blocking" if required else "warning",
            "summary": "Every edit has a resolved annotation.",
        },
        [],
    )


def validate_policy(
    source,
    candidate,
    manifest,
    manifest_raw,
    profile,
    protection,
    protection_hash,
    require_annotations,
    warnings_as_errors,
    include_snippets,
):
    if profile != "controlled":
        raise InputError("controlled is the only supported validation profile")
    edits = verify_manifest(manifest, source["data"], candidate["data"])
    checks = [
        {
            "id": "INPUT_UTF8",
            "status": "pass",
            "severity": "blocking",
            "summary": "Both inputs decoded as strict UTF-8.",
        },
        {
            "id": "MANIFEST_HASHES",
            "status": "pass",
            "severity": "blocking",
            "summary": "Whole-file and fragment hashes matched.",
        },
        {
            "id": "MANIFEST_SPANS",
            "status": "pass",
            "severity": "blocking",
            "summary": "Manifest spans are ordered, non-overlapping, and exact.",
        },
        {
            "id": "REV_SOURCE_TO_CANDIDATE",
            "status": "pass",
            "severity": "blocking",
            "summary": "Source reconstructed the candidate byte-for-byte.",
        },
        {
            "id": "REV_CANDIDATE_TO_SOURCE",
            "status": "pass",
            "severity": "blocking",
            "summary": "Candidate reconstructed the source byte-for-byte.",
        },
    ]
    findings = []

    for check_id, pattern, flags in PROTECTED_PATTERNS:
        check, new_findings = protected_result(
            check_id,
            regex_items(source["text"], source["data"], pattern, flags),
            regex_items(candidate["text"], candidate["data"], pattern, flags),
            edits,
            include_snippets,
        )
        checks.append(check)
        findings.extend(new_findings)
    for check_id, extractor in (
        ("PROT_CODE_MATH", code_math_items),
        ("PROT_TABLE", table_items),
    ):
        check, new_findings = protected_result(
            check_id,
            extractor(source["text"], source["data"]),
            extractor(candidate["text"], candidate["data"]),
            edits,
            include_snippets,
        )
        checks.append(check)
        findings.extend(new_findings)

    if protection is not None:
        source_groups = dict(custom_items(source, protection))
        candidate_groups = dict(custom_items(candidate, protection))
        all_source = []
        all_candidate = []
        for key in sorted(set(source_groups) | set(candidate_groups)):
            all_source.extend(source_groups.get(key, []))
            all_candidate.extend(candidate_groups.get(key, []))
        check, new_findings = protected_result(
            "PROT_CUSTOM",
            sorted(all_source, key=lambda item: (item["start"], item["end"])),
            sorted(all_candidate, key=lambda item: (item["start"], item["end"])),
            edits,
            include_snippets,
        )
        checks.append(check)
        findings.extend(new_findings)
    else:
        checks.append(
            {
                "id": "PROT_CUSTOM",
                "status": "not_applicable",
                "severity": "blocking",
                "summary": "No custom protection file supplied.",
            }
        )

    heading_check, heading_findings = protected_result(
        "STRUCT_HEADINGS",
        heading_items(source),
        heading_items(candidate),
        edits,
        include_snippets,
    )
    checks.append(heading_check)
    findings.extend(heading_findings)

    source_topology = list_topology(source["text"])
    candidate_topology = list_topology(candidate["text"])
    topology_passed = source_topology == candidate_topology
    checks.append(
        {
            "id": "STRUCT_LIST_TOPOLOGY",
            "status": "pass" if topology_passed else "fail",
            "severity": "blocking",
            "summary": (
                "List marker and indentation topology preserved."
                if topology_passed
                else "List marker or indentation topology changed."
            ),
        }
    )
    if not topology_passed:
        findings.append(
            {
                "rule_id": "STRUCT_LIST_TOPOLOGY",
                "summary": "List topology changed.",
                "source_sha256": sha256(
                    json.dumps(source_topology, ensure_ascii=False).encode("utf-8")
                ),
                "candidate_sha256": sha256(
                    json.dumps(candidate_topology, ensure_ascii=False).encode("utf-8")
                ),
            }
        )

    annotation_result, annotation_findings = annotation_check(
        edits, require_annotations
    )
    checks.append(annotation_result)
    findings.extend(annotation_findings)

    source_metrics = document_metrics(source)
    candidate_metrics = document_metrics(candidate)
    nonexpansion = (
        candidate_metrics["whitespace_words"] <= source_metrics["whitespace_words"]
    )
    checks.append(
        {
            "id": "GOAL_WORD_NONEXPANSION",
            "status": "pass" if nonexpansion else "fail",
            "severity": "blocking",
            "summary": (
                "Candidate did not expand in whitespace-delimited words."
                if nonexpansion
                else "Candidate expanded in whitespace-delimited words."
            ),
        }
    )
    if not nonexpansion:
        findings.append(
            {
                "rule_id": "GOAL_WORD_NONEXPANSION",
                "summary": "Candidate has more whitespace-delimited words than source.",
                "source_words": source_metrics["whitespace_words"],
                "candidate_words": candidate_metrics["whitespace_words"],
            }
        )

    has_failure = any(check["status"] == "fail" for check in checks)
    has_warning = any(check["status"] == "warning" for check in checks)
    failed = has_failure or (warnings_as_errors and has_warning)
    edit_counts = {"insert": 0, "delete": 0, "replace": 0}
    for edit in edits:
        edit_counts[edit["op"]] += 1
    source_words = source_metrics["whitespace_words"]
    candidate_words = candidate_metrics["whitespace_words"]
    reduction_basis_points = (
        None
        if source_words == 0
        else int(((source_words - candidate_words) * 10000) / source_words)
    )
    report = {
        "schema": REPORT_SCHEMA,
        "schema_version": 1,
        "status": "fail" if failed else "pass",
        "exit_code": 1 if failed else 0,
        "tool": {"name": TOOL_NAME, "version": VERSION},
        "policy": {
            "profile": profile,
            "require_annotations": require_annotations,
            "warnings_as_errors": warnings_as_errors,
            "custom_protection_sha256": protection_hash,
        },
        "source": {
            "label": source["label"],
            "sha256": sha256(source["data"]),
            "size_bytes": len(source["data"]),
        },
        "candidate": {
            "label": candidate["label"],
            "sha256": sha256(candidate["data"]),
            "size_bytes": len(candidate["data"]),
        },
        "metrics": {
            "source": source_metrics,
            "candidate": candidate_metrics,
            "delta": {
                "bytes": candidate_metrics["bytes"] - source_metrics["bytes"],
                "whitespace_words": candidate_words - source_words,
                "reduction_basis_points": reduction_basis_points,
            },
        },
        "manifest": {
            "sha256": sha256(manifest_raw),
            "edit_count": len(edits),
            "by_op": edit_counts,
            "source_to_candidate_exact": True,
            "candidate_to_source_exact": True,
        },
        "checks": checks,
        "findings": findings,
        "review_gates": {
            "mechanical_safeguards": "failed" if failed else "passed",
            "semantic_review": "outside-validator",
            "human_approval": "required",
            "unresolved_flags": "outside-validator",
        },
        "limitations": LIMITATIONS,
    }
    return report


def command_make_manifest(args):
    source = read_document(args.source)
    candidate = read_document(args.candidate)
    manifest = make_manifest_value(source, candidate)
    output_paths = [args.manifest_out, args.diff_out]
    reject_output_aliases(output_paths, [args.source, args.candidate])
    preflight_outputs(output_paths, args.force)
    write_bytes(args.manifest_out, json_bytes(manifest), args.force)
    if args.diff_out:
        difference = "".join(
            difflib.unified_diff(
                source["text"].splitlines(keepends=True),
                candidate["text"].splitlines(keepends=True),
                fromfile=source["label"],
                tofile=candidate["label"],
            )
        ).encode("utf-8")
        write_bytes(args.diff_out, difference, args.force)
    print("PASS edits={} manifest={}".format(len(manifest["edits"]), Path(args.manifest_out).name))
    return 0


def command_validate(args):
    source = read_document(args.source)
    candidate = read_document(args.candidate)
    manifest, manifest_raw = read_json(args.manifest, "manifest")
    protection, protection_hash = load_protection(args.protect)
    report = validate_policy(
        source,
        candidate,
        manifest,
        manifest_raw,
        args.profile,
        protection,
        protection_hash,
        args.require_annotations,
        args.warnings_as_errors,
        args.include_snippets,
    )
    reject_output_aliases(
        [args.report_out],
        [args.source, args.candidate, args.manifest, args.protect],
    )
    preflight_outputs([args.report_out], False)
    write_bytes(args.report_out, json_bytes(report), False)
    metrics = report["metrics"]
    reduction_basis_points = metrics["delta"]["reduction_basis_points"]
    reduction = (
        "n/a"
        if reduction_basis_points is None
        else "{:.2f}%".format(reduction_basis_points / 100.0)
    )
    has_warning = any(check["status"] == "warning" for check in report["checks"])
    print(
        "{} edits={} words={}->{} reduction={}".format(
            (
                "FAIL"
                if report["status"] != "pass"
                else "PASS_WITH_WARNINGS"
                if has_warning
                else "PASS"
            ),
            report["manifest"]["edit_count"],
            metrics["source"]["whitespace_words"],
            metrics["candidate"]["whitespace_words"],
            reduction,
        )
    )
    return report["exit_code"]


def command_apply(args):
    source = read_document(args.source)
    manifest, _raw = read_json(args.manifest, "manifest")
    verify_file_metadata(manifest, source_data=source["data"])
    edits = verified_edits(manifest, source_data=source["data"])
    output = reconstruct(source["data"], edits, "forward")
    candidate_record = manifest.get("candidate", {})
    if sha256(output) != candidate_record.get("sha256") or len(output) != candidate_record.get(
        "size_bytes"
    ):
        raise ManifestError("reconstructed candidate does not match manifest target")
    verify_manifest(manifest, source["data"], output)
    reject_output_aliases([args.output], [args.source, args.manifest])
    preflight_outputs([args.output], args.force)
    write_bytes(args.output, output, args.force)
    print("PASS edits={} output={}".format(len(edits), Path(args.output).name))
    return 0


def command_reverse(args):
    candidate = read_document(args.candidate)
    manifest, _raw = read_json(args.manifest, "manifest")
    verify_file_metadata(manifest, candidate_data=candidate["data"])
    edits = verified_edits(manifest, candidate_data=candidate["data"])
    output = reconstruct(candidate["data"], edits, "reverse")
    source_record = manifest.get("source", {})
    if sha256(output) != source_record.get("sha256") or len(output) != source_record.get(
        "size_bytes"
    ):
        raise ManifestError("reconstructed source does not match manifest target")
    verify_manifest(manifest, output, candidate["data"])
    reject_output_aliases([args.output], [args.candidate, args.manifest])
    preflight_outputs([args.output], args.force)
    write_bytes(args.output, output, args.force)
    print("PASS edits={} output={}".format(len(edits), Path(args.output).name))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Mechanical safeguards for controlled UTF-8 document tightening."
    )
    parser.add_argument(
        "--debug", action="store_true", help="show a traceback for unexpected errors"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    make_parser = subparsers.add_parser(
        "make-manifest", help="create a reversible edit manifest"
    )
    make_parser.add_argument("source")
    make_parser.add_argument("candidate")
    make_parser.add_argument("--manifest-out", required=True)
    make_parser.add_argument("--diff-out")
    make_parser.add_argument("--force", action="store_true")
    make_parser.set_defaults(handler=command_make_manifest)

    validate_parser = subparsers.add_parser(
        "validate", help="validate a supplied manifest and protected invariants"
    )
    validate_parser.add_argument("source")
    validate_parser.add_argument("candidate")
    validate_parser.add_argument("--manifest", required=True)
    validate_parser.add_argument("--report-out", required=True)
    validate_parser.add_argument(
        "--profile", choices=("controlled",), default="controlled"
    )
    validate_parser.add_argument("--protect")
    annotation_group = validate_parser.add_mutually_exclusive_group()
    annotation_group.add_argument(
        "--require-annotations",
        dest="require_annotations",
        action="store_true",
        help="require resolved annotations (the default)",
    )
    annotation_group.add_argument(
        "--allow-unannotated-draft",
        dest="require_annotations",
        action="store_false",
        help="allow a development report with annotation warnings",
    )
    validate_parser.set_defaults(require_annotations=True)
    validate_parser.add_argument("--warnings-as-errors", action="store_true")
    validate_parser.add_argument("--include-snippets", action="store_true")
    validate_parser.set_defaults(handler=command_validate)

    apply_parser = subparsers.add_parser(
        "apply", help="rebuild the manifest candidate from the source"
    )
    apply_parser.add_argument("source")
    apply_parser.add_argument("--manifest", required=True)
    apply_parser.add_argument("--output", required=True)
    apply_parser.add_argument("--force", action="store_true")
    apply_parser.set_defaults(handler=command_apply)

    reverse_parser = subparsers.add_parser(
        "reverse", help="rebuild the manifest source from the candidate"
    )
    reverse_parser.add_argument("candidate")
    reverse_parser.add_argument("--manifest", required=True)
    reverse_parser.add_argument("--output", required=True)
    reverse_parser.add_argument("--force", action="store_true")
    reverse_parser.set_defaults(handler=command_reverse)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except ManifestError as exc:
        print("ERROR manifest integrity: {}".format(exc), file=sys.stderr)
        return 4
    except InputError as exc:
        print("ERROR input: {}".format(exc), file=sys.stderr)
        return 3
    except Exception as exc:  # pragma: no cover - last-resort fail-closed boundary
        if getattr(args, "debug", False):
            traceback.print_exc()
        else:
            print("ERROR internal: {}".format(exc), file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())
