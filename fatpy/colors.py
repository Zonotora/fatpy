class Color:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    RED = "\033[93m"
    END = "\033[0m"

    @staticmethod
    def red(s):
        return Color.RED + s + Color.END

    @staticmethod
    def green(s):
        return Color.GREEN + s + Color.END

    @staticmethod
    def blue(s):
        return Color.BLUE + s + Color.END
