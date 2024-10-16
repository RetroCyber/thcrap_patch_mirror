# color_logger.py
import logging
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

# Define custom log levels
SUCCESS_LEVEL_NUM = 25
GET_LEVEL_NUM = 15

# Add custom log levels
logging.addLevelName(SUCCESS_LEVEL_NUM, "SUCC")
logging.addLevelName(GET_LEVEL_NUM, "GET")

class ColorLogger:
    def __init__(self, name=__name__):
        self.logger = logging.getLogger(name)
        handler = logging.StreamHandler()
        handler.setFormatter(self.CustomFormatter())
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.DEBUG)
        
        # Add custom logging methods
        self.logger.succ = self.succ
        self.logger.get = self.get

    # Define custom logging functions
    def succ(self, message, *args, **kws):
        if self.logger.isEnabledFor(SUCCESS_LEVEL_NUM):
            self.logger._log(SUCCESS_LEVEL_NUM, message, args, **kws)

    def get(self, message, *args, **kws):
        if self.logger.isEnabledFor(GET_LEVEL_NUM):
            self.logger._log(GET_LEVEL_NUM, message, args, **kws)

    class CustomFormatter(logging.Formatter):
        # Define format string
        format_str = "%(levelname)s: %(message)s"

        # Define colors for different levels
        LEVEL_COLORS = {
            logging.DEBUG: Fore.CYAN,
            logging.INFO: Fore.BLUE,
            logging.WARNING: Fore.YELLOW,
            logging.ERROR: Fore.RED,
            logging.CRITICAL: Fore.MAGENTA,
            SUCCESS_LEVEL_NUM: Fore.GREEN,
            GET_LEVEL_NUM: Fore.WHITE,
        }

        def format(self, record):
            levelname = record.levelname
            level_color = self.LEVEL_COLORS.get(record.levelno, "")
            format_str = f"[{level_color}%(levelname)s{Style.RESET_ALL}]   \t%(message)s"
            formatter = logging.Formatter(format_str)
            return formatter.format(record)

# Example usage within the module itself, can be removed
if __name__ == "__main__":
    logger = ColorLogger().logger
    logger.debug("This is a debug message.")
    logger.info("This is an info message.")
    logger.warning("This is a warning message.")
    logger.error("This is an error message.")
    logger.critical("This is a critical message.")
    logger.succ("This is a success message.")
    logger.get("This is a get message.")