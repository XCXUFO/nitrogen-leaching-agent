"""Read text pieces from standard Word 97–2003 compound `.doc` files.

The parser only reads the WordDocument and selected Table streams. It never
executes macros, embedded objects, or external converters.
"""
from __future__ import annotations

import struct


class LegacyWordError(ValueError):
    pass


FREE = 0xFFFFFFFF
END = 0xFFFFFFFE


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def _sector(data: bytes, index: int, size: int) -> bytes:
    start = size * (index + 1)
    if index >= FREE - 3 or start + size > len(data):
        raise LegacyWordError("Word 文件扇区损坏。")
    return data[start:start + size]


def _chain(data: bytes, start: int, table: list[int], size: int | None, *, sector_size: int,
           mini: bool = False) -> bytes:
    pieces = []
    seen = set()
    index = start
    while index != END and (size is None or len(pieces) * sector_size < size):
        if index in seen or index >= len(table) or len(pieces) * sector_size > len(data):
            raise LegacyWordError("Word 文件扇区链损坏。")
        seen.add(index)
        piece = data[index * sector_size:index * sector_size + sector_size] if mini else _sector(data, index, sector_size)
        if len(piece) != sector_size:
            raise LegacyWordError("Word 文件扇区不完整。")
        pieces.append(piece)
        index = table[index]
    if size is not None and len(pieces) * sector_size < size:
        raise LegacyWordError("Word 文件内容不完整。")
    joined = b"".join(pieces)
    return joined if size is None else joined[:size]


def _compound_streams(raw: bytes) -> dict[str, bytes]:
    if len(raw) < 512 or raw[:8] != bytes.fromhex("D0CF11E0A1B11AE1"):
        raise LegacyWordError("不是有效的旧版 Word 文件。")
    sector_size = 1 << _u16(raw, 30)
    mini_size = 1 << _u16(raw, 32)
    if sector_size not in {512, 4096} or mini_size != 64:
        raise LegacyWordError("Word 文件使用不支持的扇区格式。")
    fat_count = _u32(raw, 44)
    sector_count = len(raw) // sector_size - 1
    difat_count = _u32(raw, 72)
    if fat_count > sector_count or difat_count > sector_count:
        raise LegacyWordError("Word 文件 FAT 表大小异常。")
    fat_sectors = [_u32(raw, 76 + 4 * i) for i in range(109)]
    difat_sector = _u32(raw, 68)
    seen_difat = set()
    for _ in range(difat_count):
        if difat_sector in seen_difat:
            raise LegacyWordError("Word 文件 DIFAT 扇区链损坏。")
        seen_difat.add(difat_sector)
        block = _sector(raw, difat_sector, sector_size)
        fat_sectors.extend(_u32(block, 4 * i) for i in range(sector_size // 4 - 1))
        difat_sector = _u32(block, sector_size - 4)
    if fat_count > len(fat_sectors) or fat_count * sector_size > len(raw) * 4:
        raise LegacyWordError("Word 文件 FAT 表损坏。")
    fat = []
    for index in fat_sectors[:fat_count]:
        block = _sector(raw, index, sector_size)
        fat.extend(struct.unpack(f"<{sector_size // 4}I", block))
    directory = _chain(raw, _u32(raw, 48), fat, None, sector_size=sector_size)
    entries = {}
    root = None
    for offset in range(0, len(directory) - 127, 128):
        item = directory[offset:offset + 128]
        name_size = _u16(item, 64)
        if name_size < 2 or name_size > 64:
            continue
        name = item[:name_size - 2].decode("utf-16-le", errors="replace")
        kind = item[66]
        entry = (_u32(item, 116), _u64(item, 120))
        if kind == 5:
            root = entry
        elif kind == 2:
            entries[name] = entry
    if root is None:
        raise LegacyWordError("Word 文件目录损坏。")
    mini_stream = _chain(raw, root[0], fat, root[1], sector_size=sector_size) if root[1] else b""
    mini_fat_bytes = _chain(raw, _u32(raw, 60), fat, _u32(raw, 64) * sector_size,
                            sector_size=sector_size) if _u32(raw, 64) else b""
    mini_fat = list(struct.unpack(f"<{len(mini_fat_bytes) // 4}I", mini_fat_bytes)) if mini_fat_bytes else []
    cutoff = _u32(raw, 56)
    result = {}
    for name in ("WordDocument", "0Table", "1Table"):
        if name not in entries:
            continue
        start, size = entries[name]
        if size > len(raw) * 2:
            raise LegacyWordError("Word 文件流大小异常。")
        if size < cutoff:
            result[name] = _chain(mini_stream, start, mini_fat, size, sector_size=mini_size, mini=True)
        else:
            result[name] = _chain(raw, start, fat, size, sector_size=sector_size)
    return result


def read_legacy_word(raw: bytes) -> str:
    try:
        streams = _compound_streams(raw)
        word = streams["WordDocument"]
        if _u16(word, 0) != 0xA5EC:
            raise LegacyWordError("Word 文件版本不受支持。")
        table_name = "1Table" if _u16(word, 10) & 0x0200 else "0Table"
        table = streams[table_name]
        fc_clx, lcb_clx = _u32(word, 0x1A2), _u32(word, 0x1A6)
        clx = table[fc_clx:fc_clx + lcb_clx]
        if len(clx) != lcb_clx:
            raise LegacyWordError("Word 文件文本索引损坏。")
        offset = 0
        while offset < len(clx) and clx[offset] == 1:
            offset += 3 + _u16(clx, offset + 1)
        if offset >= len(clx) or clx[offset] != 2:
            raise LegacyWordError("Word 文件缺少文本索引。")
        plc_size = _u32(clx, offset + 1)
        plc = clx[offset + 5:offset + 5 + plc_size]
        if len(plc) != plc_size or plc_size < 16 or (plc_size - 4) % 12:
            raise LegacyWordError("Word 文件文本索引不完整。")
        count = (plc_size - 4) // 12
        cp = [_u32(plc, i * 4) for i in range(count + 1)]
        if cp[-1] - cp[0] > 300_000:
            raise LegacyWordError("Word 文件文本超过 30 万字，请拆分后上传。")
        language = _u16(word, 6)
        encoding = {0x0804: "gbk", 0x0404: "big5", 0x0411: "shift_jis"}.get(language, "cp1252")
        pieces = []
        text_length = 0
        for i in range(count):
            length = cp[i + 1] - cp[i]
            text_length += length
            if length <= 0 or text_length > 300_000:
                raise LegacyWordError("Word 文件文本长度异常。")
            fc = _u32(plc, 4 * (count + 1) + 8 * i + 2)
            compressed = bool(fc & 0x40000000)
            start = (fc & 0x3FFFFFFF) // 2 if compressed else fc & 0x3FFFFFFF
            raw_piece = word[start:start + length * (1 if compressed else 2)]
            if len(raw_piece) != length * (1 if compressed else 2):
                raise LegacyWordError("Word 文件正文不完整。")
            pieces.append(raw_piece.decode(encoding if compressed else "utf-16-le", errors="replace"))
        text = "".join(pieces).replace("\r", "\n").replace("\x07", "\t").replace("\x0c", "\n")
        return "".join(char for char in text if char >= " " or char in "\n\t")
    except (KeyError, IndexError, struct.error, UnicodeError) as exc:
        raise LegacyWordError("Word 文件结构损坏或版本不受支持。") from exc
