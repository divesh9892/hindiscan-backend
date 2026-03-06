import logging
import sys
from colorama import init, Fore, Style

# Initialize colorama to ensure Windows terminals render ANSI colors correctly
init(autoreset=True)

class ColoredFormatter(logging.Formatter):
    """Custom logging formatter injecting Colorama ANSI codes based on log level."""
    
    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record):
        log_color = self.COLORS.get(record.levelno, Fore.WHITE)
        
        # Format: [TIMESTAMP] - [LEVEL] - [FILE:LINE] - MESSAGE
        format_str = (
            f"{Fore.LIGHTBLACK_EX}%(asctime)s{Style.RESET_ALL} - "
            f"{log_color}%(levelname)s{Style.RESET_ALL} - "
            f"{Fore.LIGHTBLUE_EX}[%(filename)s:%(lineno)d]{Style.RESET_ALL} - "
            f"{log_color}%(message)s{Style.RESET_ALL}"
        )
        
        formatter = logging.Formatter(format_str, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)

def setup_logger(name="HindiExtractor", log_file="app.log"):
    """Sets up a robust enterprise logger with dual outputs (Colored Console + Plain File)."""
    logger = logging.getLogger(name)
    
    # Only configure if it doesn't already have handlers to prevent duplicate logs
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # 1. Console Handler (Colored for terminal readability)
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(ColoredFormatter())
        logger.addHandler(ch)
        
        # 2. File Handler (Plain text to avoid ANSI garbage characters in the file)
        plain_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setFormatter(plain_formatter)
        logger.addHandler(fh)
        
    return logger

# Create a global logger instance to be imported by other files
log = setup_logger()