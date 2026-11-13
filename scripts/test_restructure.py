# -*- coding: utf-8 -*-
import sys
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls

def clean_comments(doc):
    body = doc._body._element
    comments_tags = body.xpath('.//w:commentRangeStart | .//w:commentRangeEnd | .//w:commentReference')
    for tag in comments_tags:
        parent = tag.getparent()
        if parent is not None:
            parent.remove(tag)
    print(f"Removed {len(comments_tags)} comment tags.")

print("Test script ready.")
