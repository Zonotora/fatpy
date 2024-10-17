from dataclasses import dataclass
from collections import namedtuple
import struct
import sys
import re


SECTOR_LENGTH = 512
END_OF_FILE = 0xFFFF


def unpack(buffer):
    s = 0
    n = len(buffer)
    for i in range(n):
        s |= buffer[i] << (i * 8)
    return s


def pack(value, n):
    buffer = [0] * n
    for i in range(n):
        buffer[i] = value & 0xFF
        value = value >> (i * 8)
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


class Fat:
    def __init__(self, sectors, partition):
        self.sectors = sectors
        self.partition = partition
        self.bpb = BpbFat16(self.sectors[self.partition.sector])

        self.total_sectors = self.bpb.small_sector_count
        self.n_sectors_per_fat = self.bpb.n_sectors_per_fat16
        self.n_root_dir_sectors = (
            (self.bpb.n_root_entries * 32) + (self.bpb.n_bytes_per_sector - 1)
        ) // self.bpb.n_bytes_per_sector
        self.data_sectors = self.total_sectors - (
            self.bpb.n_reserved_sectors
            + (self.bpb.n_fats * self.n_sectors_per_fat)
            + self.n_root_dir_sectors
        )

        self.first_data_sector = (
            self.bpb.n_reserved_sectors
            + (self.bpb.n_fats * self.n_sectors_per_fat)
            + self.n_root_dir_sectors
            + self.partition.sector
        )
        self.first_fat_sector = self.bpb.n_reserved_sectors + self.partition.sector
        self.n_clusters = self.data_sectors // self.bpb.n_sectors_per_cluster
        # On FAT 12/16 the root directory is at a fixed position immediately after the FAT
        self.first_root_dir_sector = self.first_data_sector - self.n_root_dir_sectors

    def __str__(self):
        fields = [
            "total_sectors",
            "n_sectors_per_fat",
            "n_root_dir_sectors",
            "data_sectors",
            "n_clusters",
            "first_data_sector",
            "first_fat_sector",
            "first_root_dir_sector",
        ]

        view = ",\n".join([f"\t{field}: {getattr(self, field)}" for field in fields])
        return f"Fat(\n{view}\n)"

    def __repr__(self):
        return str(self)

    def get_bpb(self):
        return self.bpb

    def get_nonempty(self):
        index = self.partition.sector
        size = self.partition.size
        valid = []
        for i in range(index, index + size):
            has = False
            for b in self.sectors[i]:
                if b != 0:
                    has = True
                    break
            if has:
                valid.append(i)
        return valid

    def read_cluster_value_from_fat(self, cluster):
        sector = self.first_fat_sector + (cluster * 2) // self.bpb.n_bytes_per_sector
        offset_within_sector = (cluster * 2) % self.bpb.n_bytes_per_sector
        value = self.sectors[sector][offset_within_sector]
        value |= self.sectors[sector][offset_within_sector + 1] << 8
        return value

    def write_cluster_value_to_fat(self, cluster, value):
        sector = self.first_fat_sector + (cluster * 2) // self.bpb.n_bytes_per_sector
        offset_within_sector = (cluster * 2) % self.bpb.n_bytes_per_sector
        self.sectors[sector][offset_within_sector] = value
        self.sectors[sector][offset_within_sector + 1] = value >> 8

    def read_sector(self, sector_index):
        return self.sectors[sector_index]

    def write_sector(self, sector_index, offset, buffer):
        data = self.read_sector(sector_index)
        for i in range(len(buffer)):
            data[offset + i] = buffer[i]
        self.sectors[sector_index] = data

    def first_block_of_cluster(self, cluster):
        return ((cluster - 2) * self.bpb.n_sectors_per_cluster) + self.first_data_sector

    def scan_for_free_cluster(self):
        for cluster in range(self.n_clusters):
            value = self.read_cluster_value_from_fat(cluster)
            if value == 0x0000:
                return cluster

    def scan_for_free_location_in_root(self):
        sector_index = self.first_root_dir_sector
        for i in range(self.n_root_dir_sectors):
            index = sector_index + i
            sector = self.read_sector(index)

            for j in range(self.bpb.n_bytes_per_sector // 32):
                offset = j * 32
                first_cluster_lo = unpack(sector[j + 26 : j + 28])
                print(first_cluster_lo)
                if first_cluster_lo == 0:
                    print(first_cluster_lo, index, offset)
                    return index, offset
        assert False, "No more entries"

    def scan_for_free_location_in_cluster(self, cluster):
        sector_index = self.first_block_of_cluster(cluster)
        for i in range(self.bpb.n_sectors_per_cluster):
            index = sector_index + i
            sector = self.read_sector(index)

            for j in range(self.bpb.n_bytes_per_sector // 32):
                offset = j * 32
                first_cluster_lo = unpack(sector[j + 26 : j + 28])
                if first_cluster_lo == 0:
                    return index, offset
        # Need to check FAT table for the cluster to the next cluster.
        # Otherwise, allocate new cluster for this cluster entry
        next_cluster = self.read_cluster_value_from_fat(cluster)
        if next_cluster != END_OF_FILE:
            return self.scan_for_free_location_in_cluster(next_cluster)

        next_cluster = self.scan_for_free_cluster()
        self.write_cluster_value_to_fat(cluster, next_cluster)
        self.write_cluster_value_to_fat(next_cluster, END_OF_FILE),

        return self.scan_for_free_location_in_cluster(next_cluster)

    def encode_entry(self, **kwargs):
        assert len(kwargs) == len(
            fat_fields
        ), f"kwargs: {len(kwargs)} fat_fields: {len(fat_fields)}"
        buffer = [0] * 32
        for field in fat_fields:
            assert field.name in kwargs
            if field.c_string:
                buffer_value = [ord(c) for c in kwargs[field.name]]
                while len(buffer_value) < field.length:
                    buffer_value.append(0)
            else:
                buffer_value = pack(kwargs[field.name], field.length)

            for i in range(field.length):
                index = field.offset + i
                buffer[index] = buffer_value[i]
        return buffer

    def get_directory_entries(self, directory):
        if directory == "/":
            buffer = []
            n = 0
            sector_index = self.first_root_dir_sector
            for i in range(self.n_root_dir_sectors):
                index = sector_index + i
                sector = self.read_sector(index)

                for j in range(self.bpb.n_bytes_per_sector // 32):
                    offset = j * 32
                    first_cluster_lo = unpack(sector[j + 26 : j + 28])
                    if first_cluster_lo != 0:
                        buffer.extend(sector[offset : offset + 32])
                        n += 1
            return n, buffer

    def this_directory_entry(self, cluster):
        return self.encode_entry(
            **{
                "name": ".",
                "attr": DirectoryAttr.ATTR_DIRECTORY,
                "nt_res": 0,
                "creation_time_tenth": 0x01,
                "creation_time": 0x02,
                "creation_date": 0x02,
                "last_accessed_date": 0x03,
                "modified_time": 0x04,
                "modified_date": 0x05,
                "first_cluster_lo": cluster,
                "first_cluster_hi": 0,
                "file_size": 0,
            }
        )

    def parent_directory_entry(self, cluster):
        return self.encode_entry(
            **{
                "name": "..",
                "attr": DirectoryAttr.ATTR_DIRECTORY,
                "nt_res": 0,
                "creation_time_tenth": 0x01,
                "creation_time": 0x02,
                "creation_date": 0x02,
                "last_accessed_date": 0x03,
                "modified_time": 0x04,
                "modified_date": 0x05,
                "first_cluster_lo": cluster,
                "first_cluster_hi": 0,
                "file_size": 0,
            }
        )

    def create_file_or_directory(self, directory, name, attr):
        free_cluster = self.scan_for_free_cluster()
        if free_cluster == END_OF_FILE:
            return

        if name == "/":
            assert False, "directory exists"

        buffer = self.encode_entry(
            **{
                "name": name,
                "attr": attr,
                "nt_res": 0,
                "creation_time_tenth": 0x01,
                "creation_time": 0x02,
                "creation_date": 0x02,
                "last_accessed_date": 0x03,
                "modified_time": 0x04,
                "modified_date": 0x05,
                "first_cluster_lo": free_cluster,
                "first_cluster_hi": 0,
                "file_size": 0,
            }
        )
        self.write_cluster_value_to_fat(free_cluster, END_OF_FILE),
        if directory == "/":
            sector_index, offset = self.scan_for_free_location_in_root()
        else:

            parent_cluster = 0
            # sector_index, offset = self.scan_for_free_location_in_cluster(
            #     parent_cluster
            # )
        self.write_sector(sector_index, offset, buffer)

        if attr & DirectoryAttr.ATTR_DIRECTORY:
            sector_index = self.first_block_of_cluster(free_cluster)
            self.write_sector(sector_index, 0, self.this_directory_entry(free_cluster))
            self.write_sector(
                sector_index, 32, self.parent_directory_entry(free_cluster)
            )

    def create_directory(self, directory, name, attr=DirectoryAttr.ATTR_DIRECTORY):
        self.create_file_or_directory(directory, name, attr)

    def create_file(self, directory, name, attr=DirectoryAttr.ATTR_ARCHIVE):
        self.create_file_or_directory(directory, name, attr)


class Driver:
    def __init__(self, device):
        self.sectors = self.read(device)
        self.mbr = Mbr.parse(self.sectors[0])
        self.fat = {
            i: Fat(self.sectors, self.mbr.partitions[i])
            for i in range(len(self.mbr.partitions))
            if self.mbr.partitions[i].sector != 0
        }
        self.index = 0
        self.current_dir = "/"

    def read(self, device):
        sectors = []

        with open(device, mode="rb") as f:
            content = f.read()
            i = 0
            while i < len(content):
                buffer = content[i : i + SECTOR_LENGTH]
                unpacked = struct.unpack(f"{SECTOR_LENGTH}B", buffer)
                sectors.append(Sector(unpacked))
                i += SECTOR_LENGTH
        return sectors

    def write(device):
        # with open(device, mode="wb") as f:
        #     pass
        pass

    def parse(self, cmd):
        value = "unknown"
        if m := re.search(r"set ([0123])", cmd):
            self.index = int(m.group(1))
            index = int(m.group(1))
            if index not in self.fat:
                value = f"partition {index} is not formatted with fat"
        elif m := re.search(r"sec ([0-9]+)", cmd):
            index = int(m.group(1))
            if index >= len(self.sectors):
                value = f"sector {index} does not exist"
            else:
                value = self.sectors[index]
        elif cmd == "fat":
            value = self.fat[self.index]
        elif m := re.search(r"nonempty ([0123])", cmd):
            value = self.fat[self.index].get_nonempty()
        elif cmd == "mbr":
            value = self.mbr
        elif m := re.search(r"bpb ([0123])", cmd):
            value = self.fat[self.index].get_bpb()
        elif m := re.search(r"mkdir ([A-Za-z0-9]+)", cmd):
            self.fat[self.index].create_directory(self.current_dir, m.group(1))
            value = ""
        elif m := re.search(r"touch (.+)", cmd):
            pass
        elif m := re.search(r"rm (.+)", cmd):
            value = m.group(1)
        elif cmd == "ls":
            n, entries = self.fat[self.index].get_directory_entries(self.current_dir)
            names = []
            print(n)
            for i in range(n):
                entry = FatEntry(entries[i * 32 : (i + 1) * 32])
                print(entry)
                names.append(entry.name)
            value = " ".join(names)
        elif cmd == "cat":
            pass
        return value


def main():
    driver = Driver(sys.argv[1])
    while True:
        cmd = input("$ ")
        value = driver.parse(cmd)
        print(value)


if __name__ == "__main__":
    main()
