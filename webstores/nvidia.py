import logging
import logging.config
import webbrowser
from http import client
from optparse import Values

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import HTTPError
from urllib3.util.retry import Retry

## Nvidia Store - Backend Service >> Digital River (US, UK), DIHouse (RU), Rashi (IN)
# https://docs.digitalriver.com/commerce-api/ 
# https://www.digitalriver.com/docs/commerce-api-reference/

#
DR_API_KEY               = "9485fa7b159e42edb08a83bde0d83dia"
DR_PRODUCTS              = "https://api.digitalriver.com/v1/shoppers/me/products"
DR_INVENTORY_STATUS      = "https://api.digitalriver.com/v1/shoppers/me/products/{pid}/inventory-status" 
DR_ADD_TO_CART           = "https://api.digitalriver.com/v1/shoppers/me/carts/active/line-items?productId={pid}}"
DR_CART                  = "https://api.digitalriver.com/v1/shoppers/me/carts/active?productId={pid}}"

DR_PRODUCT_OUT_OF_STOCK  = "PRODUCT_INVENTORY_OUT_OF_STOCK"
DR_PRODUCT_IN_STOCK      = "PRODUCT_INVENTORY_IN_STOCK"
DR_PRODUCT_BACKORDERED   = "PRODUCT_INVENTORY_BACKORDERED"

## Nvidia Store
NV_STORE_FETCH_PRODUCTS  = "https://in-and-ru-store-api.uk-e1.cloudhub.io/DR/products/{locale}/{currency}/{pids}"
NV_STORE_FETCH_INVENTORY = "https://in-and-ru-store-api.uk-e1.cloudhub.io/DR/get-inventory/{locale}/{pid}"
NV_STORE_SESSION_TOKEN   = "https://store.nvidia.com/store/nvidia/SessionToken"
NV_ADD_TO_CART           = "ttps://store.nvidia.com/store/nvidia/{locale}}/buy/productID.{pid}/clearCart.yes/nextPage.QuickBuyCartPage"

## configure logger 
logging.config.fileConfig('logger.conf')
log = logging.getLogger(__name__)

## request headers 
HEADERS = {
    'format'    : 'json',
    'Accept'    : 'application/json',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36 Edg/85.0.564.51'
}

## Scan Product List
PRODUCT_LOOKUP = {
    'TestUnit'   : '***FOR MONITORING ONLY*** NVIDIA Test Product - GB',
    'RTX3080'    : 'NVIDIA GEFORCE RTX 3080',
    'RTX3080-GB' : 'NVIDIA GEFORCE RTX 3080 - GB',
    'RTX2080S'   : 'NVIDIA GEFORCE RTX 2080 SUPER'
}

class NvidiaStoreClient:
    locale = 'en_GB'
    currency = 'GBP'
    target_products = None
    http = None
    
    def __init__(self, locale, currency, auto_scan_products = True):
        log.info("Initialising store client with locale %s and currency %s" % (locale, currency))
        self.locale = locale
        self.currency = currency


        # setup http
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["HEAD", "GET", "OPTIONS"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.http = requests.Session()
        self.http.mount("https://", adapter)
        self.http.mount("http://", adapter)

        # prints http header
        ## http.client.HTTPConnection.debuglevel = 1

        # scan products in the catalog
        self.target_products = {} # populated after the scan
        if auto_scan_products: 
            self.scan_product_ids()

    def __del__(self):
        log.debug('StoreClient::__del__()')
        if self.http:
            self.http.close()

    def scan_product_ids(self, uri = DR_PRODUCTS):
        log.debug('StoreClient::scan_product_ids()')
        
        # scan filters 
        data = {
            'locale'    : self.locale,
            'apiKey'    : DR_API_KEY,
            'expand'    : "product",
            'fields'    : "product.id,product.displayName,product.pricing",
            'sort'      : "displayName-asc,listPrice-asc" 
        }

        try:
            resp = self.http.get(uri, headers=HEADERS, params=data)
               
            jresp = resp.json()
            log.debug('Response: %s -  %s' % (resp.status_code, jresp))

            ## process the data, scan for the required SKUs and mine the product ids 
            for product in jresp['products']['product']:
                if product['displayName'] in PRODUCT_LOOKUP.values():
                    self.target_products[str(product['id'])] = {
                        'pid' : product['id'],
                        'name' : product['displayName'],
                        'price' : product['pricing']['formattedListPrice']
                }
                
            # pagination ? traverse to next page 
            if jresp['products'].get('nextPage'):
                self.scan_product_ids(uri=jresp['products']['nextPage']['uri'])
        
        except Exception as err: 
            log.error('Could not fetch the session token - %s' %err)

    def get_target_product_ids(self):
        return self.target_products


    def get_products(self, pids):
        log.debug('StoreClient::get_products(): %s' % pids)

        products_url = NV_STORE_FETCH_PRODUCTS.format(locale=self.locale,currency=self.currency,pids=','.join(map(str, pids))) 
        log.debug('Invoking url: %s' %products_url)
        try:
            resp = requests.get(products_url)
            # parse json response
            jresp = resp.json()
            log.debug('Response - %s' % jresp)

            tracked_products = {} 
            for product in jresp['products']['product']:

                # fetch the quantity
                product_qty = self.get_product_qty(product['id'])

                tracked_products[str(product['id'])] = {
                    'pid'             : product['id'],
                    'name'            : product['name'],
                    'displayName'     : product['displayName'],
                    'sku'             : product['sku'],
                    'productInStock'  : product['inventoryStatus']['productIsInStock'],
                    'productIsTracked': product['inventoryStatus']['productIsTracked'],
                    'reqQtyAvailable' : product['inventoryStatus']['requestedQuantityAvailable'],
                    'status'          : product['inventoryStatus']['status'],
                    'shipping'        : product['customAttributes']['attribute'][9]['value'],
                    'price'           : product['pricing']['formattedListPrice'],
                    'qty'             : product_qty
                }

            return tracked_products
                      
        except HTTPError as http_err:
            log.error(f'Http error occured: {http_err}')

        except Exception as err:
            log.error(f'Error occured: {err}')

    
    def get_product_qty(self, pid):
        log.debug('StoreClient::get_product_qty(): %s' % pid)

        inventory_url = NV_STORE_FETCH_INVENTORY.format(locale=self.locale,pid=pid) 
        log.debug('Invoking url: %s' %inventory_url)

        try:
           resp = self.http.get(inventory_url)
           # parse json response
           jresp = resp.json()
           log.debug('Response - %s' % jresp)

           return jresp['Product']['availableQuantity'] 

        except HTTPError as http_err:
            log.error(f'Http error occured: {http_err}')

        except Exception as err:
            log.error(f'Error occured: {err}')

    def get_access_token(self):
        log.debug('StoreClient::get_access_token()')

        data = {
            'locale'    : self.locale,
            'currency'  : self.currency,
            'apiKey'    : DR_API_KEY 
        }

        try:
            resp = self.http.get(NV_STORE_SESSION_TOKEN, headers=HEADERS, params=data)
            jresp = resp.json()
            log.debug('Response: %s -  %s' % (resp.status_code, jresp))

            return jresp
        except Exception as err: 
            log.error('Could not fetch the session token - %s' %err)


    def get_cart(self, token):
        log.debug('StoreClient::get_cart(): %s' % token)
        ## TODO - to be done 


## Test Client
if __name__ == "__main__":
    store = NvidiaStoreClient('en_GB', 'GBP')

    # get scanned products 
    target_products = store.get_target_product_ids()
    #log.info('Target Products %s', target_products)

    # Stock Inventory Status 
    tracked_products = store.get_products([product['pid'] for product in target_products.values()])
    log.info('Tracked Products %s', tracked_products)


   # for product in target_products.values():
        # fetch the inventory
   #     status = store.get_inventory(product['pid'])
   #     product['qty'] = status['Product']['availableQuantity']
    
   # log.info('Inventory: %s' % target_products)

    #store.get_products(['5394903300,5394902000,5336531200,5256301200'])
    #store.get_access_token()
