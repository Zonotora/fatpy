import struct

from fat import Fat
from util import SECTOR_LENGTH, Mbr, Partition, Sector


class FileSystem:
    def __init__(self, device: str):
        self.sectors = self.read_disk(device)
        self.mbr = Mbr.parse(self.sectors[0])
        self.fat = {
            i: Fat(self.sectors, self.mbr.partitions[i])
            for i in range(len(self.mbr.partitions))
            if self.mbr.partitions[i].sector != 0
        }
        if len(self.fat) == 0:
            partition = Partition([0] * 16)
            partition.sector = 0
            partition.size = len(self.sectors) * SECTOR_LENGTH
            self.fat[0] = Fat(self.sectors, partition)

        self.current_dir = "/"

    def read_disk(self, device: str) -> list[Sector]:
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

    def write_disk(self, device: str):
        with open(device, mode="wb") as f:
            for sector in self.sectors:
                bytes = struct.pack(f"{SECTOR_LENGTH}B", *sector.bytes)
                f.write(bytes)

    def chdir(self):
        pass
