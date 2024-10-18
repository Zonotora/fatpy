from util import (
    BpbFat16,
    DirectoryAttr,
    DirectoryDescriptor,
    FatEntry,
    FileDescriptor,
    FileInfo,
    fat_fields,
    pack,
    unpack,
)

END_OF_FILE = 0xFFFF


def entry(name, attr, cluster):
    return {
        "name": name,
        "attr": attr,
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


def encode_entry(**kwargs):
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

        self.cwd = DirectoryDescriptor(0, self.first_root_dir_sector, None)

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

    def read_sector(self, sector_index):
        return self.sectors[sector_index]

    def write_sector(self, sector_index, offset, buffer):
        data = self.read_sector(sector_index)
        for i in range(len(buffer)):
            data[offset + i] = buffer[i]
        self.sectors[sector_index] = data

    def read_fat(self, cluster):
        sector_index = (
            self.first_fat_sector + (cluster * 2) // self.bpb.n_bytes_per_sector
        )
        offset_within_sector = (cluster * 2) % self.bpb.n_bytes_per_sector
        sector = self.read_sector(sector_index)
        value = sector[offset_within_sector]
        value |= sector[offset_within_sector + 1] << 8
        return value

    def write_fat(self, cluster, value):
        sector_index = (
            self.first_fat_sector + (cluster * 2) // self.bpb.n_bytes_per_sector
        )
        offset_within_sector = (cluster * 2) % self.bpb.n_bytes_per_sector
        buffer = [value, value >> 8]
        self.write_sector(sector_index, offset_within_sector, buffer)

    def first_sector_of_cluster(self, cluster):
        return ((cluster - 2) * self.bpb.n_sectors_per_cluster) + self.first_data_sector

    def reset_cluster(self, cluster):
        sector_index = self.first_sector_of_cluster(cluster)
        for i in range(self.bpb.n_sectors_per_cluster):
            index = sector_index + i
            buffer = [0] * self.bpb.n_bytes_per_sector
            self.write_sector(index, 0, buffer)

    def scan_fat(self):
        for cluster in range(self.n_clusters):
            value = self.read_fat(cluster)
            if value == 0x0000:
                return cluster

    def entries_in_cluster(self, cluster):
        if cluster == 0:
            first_sector_index = self.first_root_dir_sector
            n_sectors = self.n_root_dir_sectors
        else:
            first_sector_index = self.first_sector_of_cluster(cluster)
            n_sectors = self.bpb.n_bytes_per_sector

        for i in range(n_sectors):
            sector_index = first_sector_index + i
            sector = self.read_sector(sector_index)
            for j in range(self.bpb.n_bytes_per_sector // 32):
                offset = j * 32
                yield sector_index, offset, FatEntry(sector[offset : offset + 32])

    def scan_for_free_location_in_root(self):
        for sector_index, offset, entry in self.entries_in_cluster(0):
            if entry.first_cluster_lo == 0:
                return sector_index, offset

    def scan_for_free_location_in_cluster(self, cluster):
        for sector_index, offset, entry in self.entries_in_cluster(cluster):
            if entry.first_cluster_lo == 0:
                return sector_index, offset

        # Need to check FAT table for the cluster to the next cluster.
        # Otherwise, allocate new cluster for this cluster entry
        next_cluster = self.read_fat(cluster)
        if next_cluster != END_OF_FILE:
            return self.scan_for_free_location_in_cluster(next_cluster)

        next_cluster = self.scan_fat()
        self.write_fat(cluster, next_cluster)
        self.write_fat(next_cluster, END_OF_FILE),

        return self.scan_for_free_location_in_cluster(next_cluster)

    def create_file_or_directory(self, directory, name, attr):
        free_cluster = self.scan_fat()
        if free_cluster == END_OF_FILE:
            return

        if name == "/":
            assert False, "directory exists"

        buffer = encode_entry(**entry(name, attr, free_cluster))

        self.write_fat(free_cluster, END_OF_FILE),
        if directory == "/":
            sector_index, offset = self.scan_for_free_location_in_root()
        else:
            pass
            # parent_cluster = 0
            # sector_index, offset = self.scan_for_free_location_in_cluster(
            #     parent_cluster
            # )
        self.write_sector(sector_index, offset, buffer)

        if attr & DirectoryAttr.ATTR_DIRECTORY:
            self.reset_cluster(free_cluster)
            sector_index = self.first_sector_of_cluster(free_cluster)
            this_dir = encode_entry(
                **entry(".", DirectoryAttr.ATTR_DIRECTORY, free_cluster)
            )
            # TODO: free_cluster
            parent_dir = encode_entry(
                **entry("..", DirectoryAttr.ATTR_DIRECTORY, free_cluster)
            )
            self.write_sector(sector_index, 0, this_dir)
            self.write_sector(sector_index, 32, parent_dir)

    def create_directory(self, directory, name, attr=DirectoryAttr.ATTR_DIRECTORY):
        self.create_file_or_directory(directory, name, attr)

    def create_file(self, directory, name, attr=DirectoryAttr.ATTR_ARCHIVE):
        self.create_file_or_directory(directory, name, attr)

    def follow_path(self, path):
        pass

    def f_opendir(self, path) -> DirectoryDescriptor:
        pass

    def f_closedir(self, dp: DirectoryDescriptor):
        pass

    def f_readdir(self, dp: DirectoryDescriptor) -> list[FileInfo]:
        buffer = []
        for _sector_index, _offset, entry in self.entries_in_cluster(dp.cluster):
            if entry.first_cluster_lo != 0:
                file_info = FileInfo(
                    entry.file_size,
                    entry.name,
                    entry.creation_date,
                    entry.creation_time,
                    entry.attr,
                )
                buffer.append(file_info)

        return buffer

    def f_open(self, path) -> FileDescriptor:
        pass

    def f_close(self, fp: FileDescriptor):
        pass

    def f_read(self, fp: FileDescriptor):
        pass

    def f_write(self, fp: FileDescriptor):
        pass

    def f_size(self, fp: FileDescriptor):
        pass

    def f_unlink(self, path):
        """Remove file or sub-directory."""
        pass

    def f_rename(self, old_path, new_path):
        """Rename or move file or sub-directory."""
        pass

    def f_chmod(self, path, attr, mask):
        """Change attribute of file or sub-directory."""
        pass
