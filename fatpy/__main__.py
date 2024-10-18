import sys

from filesystem import FileSystem
from shell import Shell


def main():
    fs = FileSystem(sys.argv[1])
    shell = Shell(fs)
    while True:
        cmd = input("$ ")
        value = shell.parse(cmd)
        if value != "":
            print(value)


if __name__ == "__main__":
    main()
