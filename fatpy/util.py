from dataclasses import dataclass

SECTOR_LENGTH = 512


def unpack(buffer):
    s = 0
    n = len(buffer)
    for i in range(n):
        s |= buffer[i] << (i * 8)
    return s


def pack(value, n):
    buffer = [0] * n
    for i in range(n):
        value = value >> (i * 8)
        buffer[i] = value & 0xFF
    return buffer


@dataclass
class Field:
    name: str
    offset: int
    length: int
    c_string: bool = False


bpb_fields = [
    Field("jump_boot", 0, 3),
    Field("oem_name", 3, 8, c_string=True),
    Field("n_bytes_per_sector", 11, 2),
    Field("n_sectors_per_cluster", 13, 1),
    Field("n_reserved_sectors", 14, 2),
    Field("n_fats", 16, 1),
    Field("n_root_entries", 17, 2),
    Field("small_sector_count", 19, 2),
    Field("media_descriptor", 21, 1),
    Field("n_sectors_per_fat16", 22, 2),
    Field("sectors_per_track", 24, 2),
    Field("n_heads", 26, 2),
    Field("hidden_sectors", 28, 2),
    Field("large_sector_count", 32, 4),
]

bpb_fat16_fields = [
    Field("drive_number", 36, 1),
    Field("windows_nt_flags", 37, 1),
    Field("signature", 38, 1),
    Field("volume_id", 39, 4),
    Field("volume_label", 43, 11, c_string=True),
    Field("system_identifier", 54, 8, c_string=True),
]

partition_fields = [
    Field("indicator", 0, 1),
    Field("start_chs", 1, 3),
    Field("type", 4, 1),
    Field("end_chs", 5, 3),
    Field("sector", 8, 4),
    Field("size", 12, 4),
]


class DirectoryAttr:
    ATTR_READ_ONLY = 0x01
    ATTR_HIDDEN = 0x02
    ATTR_SYSTEM = 0x04
    ATTR_VOLUME_ID = 0x08
    ATTR_DIRECTORY = 0x10
    ATTR_ARCHIVE = 0x20
    ATTR_LONG_NAME = 0x0F


fat_fields = [
    Field("name", 0, 11, c_string=True),
    Field("attr", 11, 1),
    Field("nt_res", 12, 1),
    Field("creation_time_tenth", 13, 1),
    Field("creation_time", 14, 1),
    Field("creation_date", 16, 2),
    Field("last_accessed_date", 18, 2),
    Field("first_cluster_hi", 20, 2),
    Field("modified_time", 22, 2),
    Field("modified_date", 24, 2),
    Field("first_cluster_lo", 26, 2),
    Field("file_size", 28, 4),
]


class Base:
    def __init__(self, fields, buffer):
        self.fields = fields
        for field in fields:
            if field.length == 1:
                value = buffer[field.offset]
            elif field.c_string:
                chars = buffer[field.offset : field.offset + field.length]
                value = "".join([chr(c) for c in chars])
            else:
                value = unpack(buffer[field.offset : field.offset + field.length])
            setattr(self, field.name, value)

    def __str__(self):
        fields = ",\n".join(
            f"\t{field.name}: {getattr(self, field.name)}" for field in self.fields
        )
        return f"{self.__class__.__name__}(\n{fields}\n)"

    def __repr__(self):
        return str(self)


class Bpb(Base):
    def __init__(self, buffer):
        super().__init__(bpb_fields, buffer)


class BpbFat16(Base):
    def __init__(self, buffer):
        super().__init__(bpb_fields + bpb_fat16_fields, buffer)


class Partition(Base):
    def __init__(self, buffer):
        super().__init__(partition_fields, buffer)


class FatEntry(Base):
    def __init__(self, buffer):
        super().__init__(fat_fields, buffer)


@dataclass
class Mbr:
    code_area: list[int]
    partitions: list[Partition]
    signature: int

    @staticmethod
    def parse(buffer):
        code_area = buffer[:446]
        start = 446
        partitions = []
        for i in range(4):
            partition_buffer = buffer[start : start + 16]
            partition = Partition(partition_buffer)
            start += 16
            partitions.append(partition)

        signature = unpack(buffer[start:])
        mbr = Mbr(code_area, partitions, signature)
        return mbr


class Sector:
    def __init__(self, bytes):
        self.bytes = list(bytes)

    def __str__(self):
        view = "\n".join(
            [
                " ".join(
                    [
                        hex(byte)[2:].ljust(2, "0")
                        for byte in self.bytes[i * 32 : (i + 1) * 32]
                    ]
                )
                for i in range(len(self.bytes) // 32)
            ]
        )
        return view

    def __repr__(self):
        return str(self)

    def __getitem__(self, index):
        return self.bytes[index]

    def __setitem__(self, index, value):
        self.bytes[index] = value


class Descriptor:
    def __init__(self):
        self.sector = 0
        self.cluster = 0
        self.attr = 0


class DirectoryDescriptor(Descriptor):
    def __init__(self):
        super().__init__()


class FileDescriptor(Descriptor):
    def __init__(self):
        super().__init__()
        self.dir_sector = 0
        self.size = 0
