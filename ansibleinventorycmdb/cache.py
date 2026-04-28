# Cache instance module

from flask_caching import Cache

CACHE_TIMEOUT = 600

cache_config = {
    "CACHE_TYPE": "SimpleCache",  # Flask-Caching related configs
    "CACHE_DEFAULT_TIMEOUT": CACHE_TIMEOUT,  # 5 minutes default timeout for cache
}
cache = Cache(config=cache_config)  # Create a cache object, we will init it with the app in create_app()
