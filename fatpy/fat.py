from util import BpbFat16, DirectoryAttr, fat_fields, pack, unpack

END_OF_FILE = 0xFFFF


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

    def get_index_and_offset_within_sector(self, index):
        sector = self.read_sector(index)
        for j in range(self.bpb.n_bytes_per_sector // 32):
            offset = j * 32
            first_cluster_lo = unpack(sector[offset + 26 : offset + 28])
            if first_cluster_lo == 0:
                return index, offset
        return None

    def scan_for_free_location_in_root(self):
        sector_index = self.first_root_dir_sector
        for i in range(self.n_root_dir_sectors):
            index = sector_index + i
            if ret := self.get_index_and_offset_within_sector(index):
                return ret

        assert False, "No more entries"

    def scan_for_free_location_in_cluster(self, cluster):
        sector_index = self.first_block_of_cluster(cluster)
        for i in range(self.bpb.n_sectors_per_cluster):
            index = sector_index + i
            if ret := self.get_index_and_offset_within_sector(index):
                return ret

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
                    first_cluster_lo = unpack(sector[offset + 26 : offset + 28])
                    if first_cluster_lo != 0:
                        buffer.extend(sector[offset : offset + 32])
                        n += 1
            return n, buffer

    def reset_cluster(self, cluster):
        sector_index = self.first_block_of_cluster(cluster)
        for i in range(self.bpb.n_sectors_per_cluster):
            index = sector_index + i
            buffer = [0] * self.bpb.n_bytes_per_sector
            self.write_sector(index, 0, buffer)

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
                "creation_date": 0x0101,
                "last_accessed_date": 0x04,
                "modified_time": 0x05,
                "modified_date": 0x06,
                "first_cluster_lo": free_cluster,
                "first_cluster_hi": 0,
                "file_size": 0,
            }
        )
        self.write_cluster_value_to_fat(free_cluster, END_OF_FILE),
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
            sector_index = self.first_block_of_cluster(free_cluster)
            self.write_sector(sector_index, 0, self.this_directory_entry(free_cluster))
            self.write_sector(
                sector_index, 32, self.parent_directory_entry(free_cluster)
            )

    def create_directory(self, directory, name, attr=DirectoryAttr.ATTR_DIRECTORY):
        self.create_file_or_directory(directory, name, attr)

    def create_file(self, directory, name, attr=DirectoryAttr.ATTR_ARCHIVE):
        self.create_file_or_directory(directory, name, attr)
