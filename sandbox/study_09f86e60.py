import logging
import time
from logging.handlers import RotatingFileHandler

# Create a logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create a rotating file handler
file_handler = RotatingFileHandler('app.log', maxBytes=1024*1024*10, backupCount=5)
file_handler.setLevel(logging.DEBUG)

# Create a console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Create a formatter and attach it to the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)

def monitor_system():
    while True:
        logger.debug('System is running')
        logger.info('System is running')
        logger.warning('System is running with warnings')
        logger.error('System is running with errors')
        logger.critical('System is running with critical errors')
        time.sleep(1)

if __name__ == '__main__':
    monitor_system()