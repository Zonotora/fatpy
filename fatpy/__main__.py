import argparse
import atexit
import sys

from filesystem import FileSystem
from shell import Shell


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("device")
    parser.add_argument("-w", "--write", action="store_true")

    return parser.parse_args()


def main():
    args = parse_args()
    fs = FileSystem(args.device)
    shell = Shell(fs)

    def exit_handler():
        fs.write_disk(args.device)

    if args.write:
        atexit.register(exit_handler)

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
