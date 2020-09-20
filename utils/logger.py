import logging 
import logging.config


# Configure the logger 
logging.config.fileConfig('logger.conf')
log = logging.getLogger(__name__)