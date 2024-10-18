import struct

from fat import Fat
from util import SECTOR_LENGTH, FileDescriptor, Mbr, Sector


class FileSystem:
    def __init__(self, device):
        self.sectors = self.read_disk(device)
        self.mbr = Mbr.parse(self.sectors[0])
        self.fat = {
            i: Fat(self.sectors, self.mbr.partitions[i])
            for i in range(len(self.mbr.partitions))
            if self.mbr.partitions[i].sector != 0
        }
        self.index = 0
        self.current_dir = "/"

    def read_disk(self, device):
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

    def write_disk(device):
        # with open(device, mode="wb") as f:
        #     pass
        pass

    def chdir(self):
        pass

    def f_open(self) -> FileDescriptor:
        pass

    def f_close(self, fp: FileDescriptor):
        pass

    def f_read(self, fp: FileDescriptor):
        pass

    def f_write(self, fp: FileDescriptor):
        pass

    def f_size(self, fp: FileDescriptor):
        pass
