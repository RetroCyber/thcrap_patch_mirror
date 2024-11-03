# color_logger.py
import logging
from logging.handlers import TimedRotatingFileHandler
from colorama import Fore, Style, init
import os
from datetime import datetime


# Initialize colorama
init(autoreset=True)

# Define custom log levels
SUCCESS_LEVEL_NUM = 25
GET_LEVEL_NUM = 15
UPDATE_LEVEL_NUM = 35
REMOVE_LEVEL_NUM = 45

# Add custom log levels
logging.addLevelName(SUCCESS_LEVEL_NUM, "SUCC")
logging.addLevelName(GET_LEVEL_NUM, "GET")
logging.addLevelName(UPDATE_LEVEL_NUM, "UPDATE")
logging.addLevelName(REMOVE_LEVEL_NUM, "REMOVE")

class ColorLogger:
    def __init__(self, name=__name__, log_to_file=False, log_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(self.CustomFormatter())
        self.logger.addHandler(console_handler)
        
        # File handler
        if log_to_file:
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            log_filename = os.path.join(log_dir, f"{datetime.now().strftime('%Y-%m-%d')}.log")
            file_handler = TimedRotatingFileHandler(log_filename, when='midnight', interval=1, backupCount=7)
            file_handler.suffix = "%Y-%m-%d"
            file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            self.logger.addHandler(file_handler)
        
        # Add custom logging methods
        self.logger.succ = self.succ
        self.logger.get = self.get
        self.logger.update = self.update
        self.logger.remove = self.remove

    # Define custom logging functions
    def succ(self, message, *args, **kws):
        if self.logger.isEnabledFor(SUCCESS_LEVEL_NUM):
            self.logger._log(SUCCESS_LEVEL_NUM, message, args, **kws)

    def get(self, message, *args, **kws):
        if self.logger.isEnabledFor(GET_LEVEL_NUM):
            self.logger._log(GET_LEVEL_NUM, message, args, **kws)

    def update(self, message, *args, **kws):
        if self.logger.isEnabledFor(UPDATE_LEVEL_NUM):
            self.logger._log(UPDATE_LEVEL_NUM, message, args, **kws)

    def remove(self, message, *args, **kws):
        if self.logger.isEnabledFor(REMOVE_LEVEL_NUM):
            self.logger._log(REMOVE_LEVEL_NUM, message, args, **kws)

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
            UPDATE_LEVEL_NUM: Fore.GREEN,
            REMOVE_LEVEL_NUM: Fore.RED,
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