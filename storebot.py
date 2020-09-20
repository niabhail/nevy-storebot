from webstores.nvidia import NvidiaStore
from utils.logger import log


if __name__ == "__main__":

    store = NvidiaStore('en_GB', 'GBP')

    # get scanned products 
    target_products = store.get_target_product_ids()
    #log.info('Target Products %s', target_products)

    # Stock Inventory Status 
    tracked_products = store.get_products([product['pid'] for product in target_products.values()])
    log.info('Tracked Products %s', tracked_products)
