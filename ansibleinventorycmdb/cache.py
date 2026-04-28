# Cache instance module

from flask_caching import Cache

cache_config = {
    "CACHE_TYPE": "SimpleCache",  # Flask-Caching related configs
    "CACHE_DEFAULT_TIMEOUT": 300,  # 5 minutes default timeout for cache
}
cache = Cache(config=cache_config)  # Create a cache object, we will init it with the app in create_app()
