import sys

from filesystem import FileSystem
from shell import Shell


def main():
    fs = FileSystem(sys.argv[1])
    shell = Shell(fs)
    while True:
        cmd = input("$ ")
        try:
            value = shell.parse(cmd)
        except Exception as e:
            value = e
        if value != "":
            print(value)


if __name__ == "__main__":
    main()
