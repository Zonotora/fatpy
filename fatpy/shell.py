import re

from colors import Color
from filesystem import FileSystem
from util import DirectoryAttr, FatEntry


class Shell:
    def __init__(self, fs: FileSystem):
        self.fs = fs
        self.index = 0

    def parse(self, cmd):
        value = "unknown"
        if m := re.search(r"set ([0123])", cmd):
            self.index = int(m.group(1))
            index = int(m.group(1))
            if index not in self.fs.fat:
                value = f"partition {index} is not formatted with fat"
        elif m := re.search(r"sec ([0-9]+)", cmd):
            index = int(m.group(1))
            if index >= len(self.sectors):
                value = f"sector {index} does not exist"
            else:
                value = self.sectors[index]
        elif cmd == "fat":
            value = self.fs.fat[self.index]
        elif m := re.search(r"nonempty ([0123])", cmd):
            value = self.fs.fat[self.index].get_nonempty()
        elif cmd == "mbr":
            value = self.mbr
        elif m := re.search(r"bpb ([0123])", cmd):
            value = self.fs.fat[self.index].get_bpb()
        elif m := re.search(r"mkdir ([A-Za-z0-9]+)", cmd):
            self.fs.fat[self.index].create_directory(self.fs.current_dir, m.group(1))
            value = ""
        elif m := re.search(r"touch (.+)", cmd):
            pass
        elif m := re.search(r"rm (.+)", cmd):
            value = m.group(1)
        elif cmd == "ls":
            n, entries = self.fs.fat[self.index].get_directory_entries(
                self.fs.current_dir
            )
            names = []
            for i in range(n):
                entry = FatEntry(entries[i * 32 : (i + 1) * 32])
                print(entry)
                if entry.attr & DirectoryAttr.ATTR_DIRECTORY:
                    names.append(Color.blue(entry.name))
                else:
                    names.append(entry.name)
            value = " ".join(names)
        elif cmd == "cat":
            pass
        return value
