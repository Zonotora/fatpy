import re

from colors import Color
from filesystem import FileSystem
from util import DirectoryAttr, DirectoryDescriptor


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
            if index >= len(self.fs.sectors):
                value = f"sector {index} does not exist"
            else:
                value = self.fs.sectors[index]
        elif cmd == "fat":
            value = self.fs.fat[self.index]
        elif cmd == "nonempty":
            value = self.fs.fat[self.index].get_nonempty()
        elif cmd == "mbr":
            value = self.fs.mbr
        elif cmd == "cwd":
            value = self.fs.fat[self.index].cwd
        elif cmd == "bpb":
            value = self.fs.fat[self.index].get_bpb()
        elif m := re.search(r"mkdir ([A-Za-z0-9\/]+)", cmd):
            self.fs.fat[self.index].f_opendir(m.group(1))
            value = ""
        elif m := re.search(r"cd ([A-Za-z0-9\.\/]+)", cmd):
            self.fs.fat[self.index].chdir(m.group(1))
            value = ""
        elif m := re.search(r"touch (.+)", cmd):
            pass
        elif m := re.search(r"rm (.+)", cmd):
            value = m.group(1)
        elif cmd == "ls":
            fs = self.fs.fat[self.index].f_readdir(self.fs.fat[self.index].cwd)
            names = []
            for i in range(len(fs)):
                if fs[i].attr & DirectoryAttr.ATTR_DIRECTORY:
                    names.append(Color.blue(fs[i].name))
                else:
                    names.append(fs[i].name)
            value = " ".join(names)
        elif cmd == "cat":
            pass
        return value
