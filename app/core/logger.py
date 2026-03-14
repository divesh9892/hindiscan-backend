import logging
import sys
import contextvars
from colorama import init, Fore, Style

# Initialize colorama to ensure Windows terminals render ANSI colors correctly
init(autoreset=True)

# 🚀 THE VAULT: This creates an isolated memory bubble for the current async task.
# Defaults to "System" for background tasks or server startup logs.
request_user_ctx = contextvars.ContextVar("request_user", default="System")

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
        
        # 🚀 Fetch the highly-isolated user context
        current_user = request_user_ctx.get()
        
        # Format: [TIMESTAMP] - [LEVEL] - [USER] - [FILE:LINE] - MESSAGE
        format_str = (
            f"{Fore.LIGHTBLACK_EX}%(asctime)s{Style.RESET_ALL} - "
            f"{log_color}%(levelname)s{Style.RESET_ALL} - "
            f"{Fore.MAGENTA}[{current_user}]{Style.RESET_ALL} - " # 🚀 Injects the user in Magenta
            f"{Fore.LIGHTBLUE_EX}[%(filename)s:%(lineno)d]{Style.RESET_ALL} - "
            f"{log_color}%(message)s{Style.RESET_ALL}"
        )
        
        formatter = logging.Formatter(format_str, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)

class PlainContextFormatter(logging.Formatter):
    """Ensures the plain file logger also gets the dynamic context without ANSI garbage."""
    def format(self, record):
        current_user = request_user_ctx.get()
        self._style._fmt = f'%(asctime)s - %(levelname)s - [{current_user}] - [%(filename)s:%(lineno)d] - %(message)s'
        return super().format(record)

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
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setFormatter(PlainContextFormatter())
        logger.addHandler(fh)
        
    return logger

# Create a global logger instance to be imported by other files
log = setup_logger()