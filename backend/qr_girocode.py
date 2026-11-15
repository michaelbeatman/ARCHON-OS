"""Pure-Python ISO/IEC 18004 QR Code (ECC Level M) & EPC069-12 GiroCode SVG generator.

Zero external dependencies: generates deterministic, scannable EPC-QR GiroCodes
for German/SEPA invoices (``BCD\\n002\\n1\\nSCT\\n...``) directly as crisp SVG.
"""

from __future__ import annotations

import html
import re
from typing import List, Tuple

# Galois Field GF(2^8) with primitive polynomial x^8 + x^4 + x^3 + x^2 + 1 (0x11D)
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256


def _init_gf() -> None:
    x = 1
    for i in range(255):
        _GF_EXP[i] = x
        _GF_LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _GF_EXP[i] = _GF_EXP[i - 255]


_init_gf()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator_poly(degree: int) -> List[int]:
    poly = [1]
    for i in range(degree):
        # Multiply poly by (x - alpha^i) = [1, _GF_EXP[i]]
        nxt = [0] * (len(poly) + 1)
        a = _GF_EXP[i]
        for j, c in enumerate(poly):
            nxt[j] ^= c
            nxt[j + 1] ^= _gf_mul(c, a)
        poly = nxt
    return poly


def _rs_encode(data: List[int], ec_count: int) -> List[int]:
    gen = _rs_generator_poly(ec_count)
    res = list(data) + [0] * ec_count
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            for j in range(1, len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data) :]


# ISO 18004 ECC Level M parameters for Versions 1..10:
# (version, total_data_codewords, ec_codewords_per_block, group1_blocks, group1_data, group2_blocks, group2_data)
_ECC_M_TABLE: List[Tuple[int, int, int, int, int, int, int]] = [
    (1, 16, 10, 1, 16, 0, 0),
    (2, 28, 16, 1, 28, 0, 0),
    (3, 44, 26, 1, 44, 0, 0),
    (4, 64, 18, 2, 32, 0, 0),
    (5, 86, 24, 2, 43, 0, 0),
    (6, 108, 16, 4, 27, 0, 0),
    (7, 124, 18, 4, 31, 0, 0),
    (8, 154, 22, 2, 38, 2, 39),
    (9, 182, 22, 3, 36, 2, 37),
    (10, 216, 26, 4, 43, 1, 44),
]

# Alignment pattern center coordinates per version (ISO 18004 Annex E)
_ALIGN_CENTERS: dict[int, List[int]] = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}

# Version info bitstrings (Versions 7..10, BCH(18,6) encoded)
_VERSION_INFO = {
    7: 0x07C94,
    8: 0x085BC,
    9: 0x09A99,
    10: 0x0A4D3,
}


def _select_version(payload_len: int) -> Tuple[int, int, int, int, int, int, int]:
    # Byte mode uses 4-bit mode + 8-bit count (v1..v9) or 16-bit count (v10) + 4-bit terminator
    for row in _ECC_M_TABLE:
        ver, total_data, *_ = row
        count_bits = 8 if ver <= 9 else 16
        max_bytes = (total_data * 8 - 4 - count_bits) // 8
        if payload_len <= max_bytes:
            return row
    raise ValueError(f"QR payload too long for v1..v10 ECC-M ({payload_len} bytes)")


def _encode_codewords(raw: bytes) -> Tuple[int, List[int]]:
    ver, total_data, ec_per_block, g1_blk, g1_data, g2_blk, g2_data = _select_version(len(raw))
    bits: List[int] = []

    def push_bits(val: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            bits.append((val >> shift) & 1)

    push_bits(0b0100, 4)  # Byte mode
    push_bits(len(raw), 8 if ver <= 9 else 16)
    for b in raw:
        push_bits(b, 8)

    cap_bits = total_data * 8
    term_len = min(4, cap_bits - len(bits))
    bits.extend([0] * term_len)
    while len(bits) % 8 != 0:
        bits.append(0)

    data_bytes: List[int] = []
    for i in range(0, len(bits), 8):
        byte = 0
        for bit in bits[i : i + 8]:
            byte = (byte << 1) | bit
        data_bytes.append(byte)

    pad_cycle = (0xEC, 0x11)
    idx = 0
    while len(data_bytes) < total_data:
        data_bytes.append(pad_cycle[idx & 1])
        idx += 1

    # Split into RS blocks
    blocks_data: List[List[int]] = []
    blocks_ec: List[List[int]] = []
    pos = 0
    for count, size in ((g1_blk, g1_data), (g2_blk, g2_data)):
        for _ in range(count):
            blk = data_bytes[pos : pos + size]
            pos += size
            blocks_data.append(blk)
            blocks_ec.append(_rs_encode(blk, ec_per_block))

    # Interleave data codewords, then EC codewords
    codewords: List[int] = []
    max_data_len = max(len(b) for b in blocks_data)
    for i in range(max_data_len):
        for b in blocks_data:
            if i < len(b):
                codewords.append(b[i])
    for i in range(ec_per_block):
        for ec in blocks_ec:
            if i < len(ec):
                codewords.append(ec[i])
    return ver, codewords


def _build_matrix(ver: int, codewords: List[int]) -> List[List[int]]:
    size = 17 + 4 * ver
    # -1 = unassigned; 0/1 = light/dark function or data module
    mat = [[-1] * size for _ in range(size)]
    is_func = [[False] * size for _ in range(size)]

    def set_func(r: int, c: int, val: int) -> None:
        if 0 <= r < size and 0 <= c < size:
            mat[r][c] = val
            is_func[r][c] = True

    def draw_finder(top: int, left: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = top + dr, left + dc
                if not (0 <= r < size and 0 <= c < size):
                    continue
                if dr in (-1, 7) or dc in (-1, 7):
                    set_func(r, c, 0)
                elif dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4):
                    set_func(r, c, 1)
                else:
                    set_func(r, c, 0)

    draw_finder(0, 0)
    draw_finder(0, size - 7)
    draw_finder(size - 7, 0)

    # Alignment patterns
    centers = _ALIGN_CENTERS.get(ver, [])
    for cr in centers:
        for cc in centers:
            if (cr <= 8 and cc <= 8) or (cr <= 8 and cc >= size - 9) or (cr >= size - 9 and cc <= 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    val = 1 if (abs(dr) == 2 or abs(dc) == 2 or (dr == 0 and dc == 0)) else 0
                    set_func(cr + dr, cc + dc, val)

    # Timing patterns
    for i in range(8, size - 8):
        bit = 1 if (i % 2 == 0) else 0
        if not is_func[6][i]:
            set_func(6, i, bit)
        if not is_func[i][6]:
            set_func(i, 6, bit)

    # Dark module
    set_func(size - 8, 8, 1)

    # Reserve format info areas
    for i in range(9):
        if i != 6:
            is_func[8][i] = True
            is_func[i][8] = True
    for i in range(8):
        is_func[8][size - 1 - i] = True
        is_func[size - 1 - i][8] = True

    # Version info for v >= 7
    if ver >= 7:
        vbits = _VERSION_INFO[ver]
        for i in range(18):
            bit = (vbits >> i) & 1
            r = i // 3
            c = size - 11 + (i % 3)
            set_func(r, c, bit)
            set_func(c, r, bit)

    # Place data bits in upward/downward zig-zag pairs
    bit_stream: List[int] = []
    for cw in codewords:
        for shift in range(7, -1, -1):
            bit_stream.append((cw >> shift) & 1)

    bit_idx = 0
    upward = True
    col = size - 1
    while col >= 1:
        if col == 6:
            col -= 1
        row_iter = range(size - 1, -1, -1) if upward else range(size)
        for row in row_iter:
            for dc in (0, -1):
                c = col + dc
                if not is_func[row][c]:
                    val = bit_stream[bit_idx] if bit_idx < len(bit_stream) else 0
                    bit_idx += 1
                    mat[row][c] = val
        upward = not upward
        col -= 2

    # Choose optimal mask (0..7)
    def mask_cond(m: int, r: int, c: int) -> bool:
        if m == 0:
            return (r + c) % 2 == 0
        if m == 1:
            return r % 2 == 0
        if m == 2:
            return c % 3 == 0
        if m == 3:
            return (r + c) % 3 == 0
        if m == 4:
            return ((r // 2) + (c // 3)) % 2 == 0
        if m == 5:
            return ((r * c) % 2) + ((r * c) % 3) == 0
        if m == 6:
            return (((r * c) % 2) + ((r * c) % 3)) % 2 == 0
        return (((r + c) % 2) + ((r * c) % 3)) % 2 == 0

    def apply_mask_and_format(m: int) -> List[List[int]]:
        grid = [[mat[r][c] for c in range(size)] for r in range(size)]
        for r in range(size):
            for c in range(size):
                if not is_func[r][c] and mask_cond(m, r, c):
                    grid[r][c] ^= 1

        # ECC Level M (00) + 3-bit mask -> BCH(15,5) ^ 0x5412
        fmt_data = (0b00 << 3) | m
        rem = fmt_data << 10
        gen = 0b10100110111
        for shift in range(4, -1, -1):
            if rem & (1 << (shift + 10)):
                rem ^= gen << shift
        fmt_bits = ((fmt_data << 10) | rem) ^ 0x5412

        # Horizontal + Vertical format strips
        top_left_coords_h = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
                             (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
        other_coords = [
            (size - 1, 8), (size - 2, 8), (size - 3, 8), (size - 4, 8),
            (size - 5, 8), (size - 6, 8), (size - 7, 8),
            (8, size - 8), (8, size - 7), (8, size - 6), (8, size - 5),
            (8, size - 4), (8, size - 3), (8, size - 2), (8, size - 1),
        ]
        for idx_bit in range(15):
            b = (fmt_bits >> (14 - idx_bit)) & 1
            r1, c1 = top_left_coords_h[idx_bit]
            r2, c2 = other_coords[idx_bit]
            grid[r1][c1] = b
            grid[r2][c2] = b
        return grid

    def penalty(grid: List[List[int]]) -> int:
        score = 0
        # Run penalty
        for r in range(size):
            run = 1
            for c in range(1, size):
                if grid[r][c] == grid[r][c - 1]:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + (run - 5)
                    run = 1
            if run >= 5:
                score += 3 + (run - 5)
        for c in range(size):
            run = 1
            for r in range(1, size):
                if grid[r][c] == grid[r - 1][c]:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + (run - 5)
                    run = 1
            if run >= 5:
                score += 3 + (run - 5)
        # 2x2 blocks
        for r in range(size - 1):
            for c in range(size - 1):
                v = grid[r][c]
                if grid[r][c + 1] == v and grid[r + 1][c] == v and grid[r + 1][c + 1] == v:
                    score += 3
        return score

    best_grid = None
    best_score = None
    for m in range(8):
        candidate = apply_mask_and_format(m)
        sc = penalty(candidate)
        if best_score is None or sc < best_score:
            best_score = sc
            best_grid = candidate
    return best_grid  # type: ignore[return-value]


def generate_qr_matrix(payload: str) -> List[List[int]]:
    """Encodes a UTF-8 string into an ECC Level M QR matrix (0=white, 1=black)."""
    raw = str(payload or "").encode("utf-8")
    ver, codewords = _encode_codewords(raw)
    return _build_matrix(ver, codewords)


def build_epc_qr_payload(
    *,
    recipient_name: str,
    iban: str,
    amount_eur: float,
    currency: str = "EUR",
    bic: str = "",
    reference: str = "",
    remittance_text: str = "",
) -> str:
    """Builds a standard EPC069-12 GiroCode payload string (EUR only)."""
    clean_currency = str(currency or "EUR").strip().upper()
    if clean_currency != "EUR":
        raise ValueError(f"EPC069-12 GiroCode unterstützt ausschließlich EUR (erhalten: {clean_currency})")
    clean_iban = re.sub(r"\s+", "", str(iban or "")).upper()
    clean_bic = re.sub(r"\s+", "", str(bic or "")).upper()[:11]
    clean_name = re.sub(r"[\r\n]+", " ", str(recipient_name or "")).strip()[:70]
    amt = max(0.01, min(999999999.99, float(amount_eur or 0.0)))
    clean_ref = re.sub(r"[\r\n]+", " ", str(reference or "")).strip()[:35]
    clean_txt = re.sub(r"[\r\n]+", " ", str(remittance_text or "")).strip()[:140]
    if clean_ref and clean_txt:
        # EPC069-12 allows structured reference OR unstructured remittance text (not both)
        clean_txt = ""
    return "\n".join([
        "BCD",
        "002",
        "1",
        "SCT",
        clean_bic,
        clean_name,
        clean_iban,
        f"EUR{amt:.2f}",
        "",
        clean_ref,
        clean_txt,
    ])


def render_qr_svg(payload: str, size_px: int = 96, title: str = "GiroCode EPC-QR") -> str:
    """Renders ``payload`` into a compact standalone ``<svg>`` QR code with quiet zone."""
    matrix = generate_qr_matrix(payload)
    dim = len(matrix)
    quiet = 2
    total = dim + quiet * 2
    path_parts: List[str] = []
    for r, row in enumerate(matrix):
        for c, cell in enumerate(row):
            if cell:
                path_parts.append(f"M{c + quiet},{r + quiet}h1v1h-1z")
    d_attr = "".join(path_parts)
    px = max(48, min(320, int(size_px)))
    safe_title = html.escape(str(title or "GiroCode EPC-QR"), quote=True)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
        f'width="{px}" height="{px}" role="img" aria-label="{safe_title}" shape-rendering="crispEdges">'
        f'<title>{safe_title}</title>'
        f'<rect width="{total}" height="{total}" fill="#ffffff"/>'
        f'<path d="{d_attr}" fill="#0f172a"/>'
        f"</svg>"
    )
