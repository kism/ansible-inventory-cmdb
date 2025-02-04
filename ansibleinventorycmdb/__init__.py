"""Flask webapp ansibleinventorycmdb."""

from pprint import pformat

from flask import Flask

from . import bp_cmdb, config, logger

__version__ = "1.0.1"  # This is the version of the app, used in pyproject.toml, enforced in a test.


def create_app(test_config: dict | None = None, instance_path: str | None = None) -> Flask:
    """Create and configure an instance of the Flask application."""
    app = Flask(__name__, instance_relative_config=True, instance_path=instance_path)  # Create Flask app object

    logger.setup_logger(app, config.DEFAULT_CONFIG["logging"])  # Setup logger with defaults defined in config module

    if test_config:  # For Python testing we will often pass in a config
        if not instance_path:
            app.logger.critical("When testing supply both test_config and instance_path!")
            raise AttributeError(instance_path)
        aic_conf = config.AnsibleInventoryCmdbConfig(config=test_config, instance_path=app.instance_path)
    else:
        aic_conf = config.AnsibleInventoryCmdbConfig(instance_path=app.instance_path)  # Loads app config from disk

    app.logger.debug("Instance path is: %s", app.instance_path)

    logger.setup_logger(app, aic_conf["logging"])  # Setup logger with config

    # Flask config, at the root of the config object.
    app.config.from_mapping(aic_conf["flask"])

    # Other sections handled by config.py
    for key, value in aic_conf.items():
        if key != "flask":
            app.config[key] = value

    # Do some debug logging of config
    app_config_str = ">>>\nFlask config:"
    for key, value in app.config.items():
        app_config_str += f"\n  {key}: {pformat(value)}"

    app.logger.debug(app_config_str)

    # Now that we have loaded out configuration, we can import our blueprints
    # KISM-BOILERPLATE: This is a demo blueprint blueprint_one.py. Rename the file
    #  and vars to make your own http endpoints and pages. Use multiple blueprints if
    #  you have functionality you can categorise.
    app.register_blueprint(bp_cmdb.bp)  # Register blueprint

    # For modules that need information from the app object we need to start them under `with app.app_context():`
    # Since in the blueprint_one module, we use `from flask import current_app` to get the app object to get the config
    with app.app_context():
        bp_cmdb.start_cmdb_bp()

    app.logger.info("Starting Web Server")

    return app
