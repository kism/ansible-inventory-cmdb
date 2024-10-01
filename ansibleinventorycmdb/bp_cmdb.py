"""Blueprint one's object..."""

import logging

import yaml
from flask import Blueprint, Response, current_app, jsonify, render_template

from ansibleinventorycmdb.cmdb import AnsibleCMDB

# Modules should all setup logging like this so the log messages include the modules name.
# If you were to list all loggers with something like...
# `loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]`
# Before creating this object, you would not see a logger with this modules name (ansibleinventorycmdb.this_module_name)
logger = logging.getLogger(
    __name__
)  # Create a logger: ansibleinventorycmdb.this_module_name, inherit config from root logger

# Register this module (__name__) as available to the blueprints of ansibleinventorycmdb, I think https://flask.palletsprojects.com/en/3.0.x/blueprints/
bp = Blueprint("ansibleinventorycmdb", __name__)

cmdb: AnsibleCMDB | None = None


# KISM-BOILERPLATE:
# So regarding current_app, have a read of https://flask.palletsprojects.com/en/3.0.x/appcontext/
# This function is a bit of a silly example, but often you need to do things to initialise the module.
# You can't use the current_app object outside of a function since it behaves a bit weird, even if
#   you import the module under `with app.app_context():`
# So we call this to set globals in this module.
# You don't need to use this to set every variable as current_app will work fine in any function.
def start_blueprint_one() -> None:
    """Method to 'configure' this module. Needs to be called under `with app.app_context():` from __init__.py."""
    global cmdb  # noqa: PLW0603 Necessary evil as far as I can tell, could move to all objects but eh...

    cmdb = AnsibleCMDB(current_app.config["cmdb"]["inventory_url"])  # Create an instance of our CMDB class


# Flask homepage, generally don't have this as a blueprint.
@bp.route("/")
def home() -> str:
    """Flask home."""
    assert cmdb is not None

    schema_mapping = current_app.config["cmdb"]["schema_mapping"]

    for mapping, nice_text in schema_mapping.items():
        logger.info(f"Mapping: {mapping} -> {nice_text}")

    return render_template(
        "home.html.j2", __app_nice_name="Ansible Inventory CMDB", cmdb=cmdb.get(), schema_mapping=schema_mapping
    )  # Return a webpage


@bp.route("/host/<string:host>")
def host(host: str) -> Response:
    """Return a JSON response for a host."""
    assert cmdb is not None

    # Get copy of cmdb host vars in alphabetical order
    alphabetical_var_dict = dict(sorted(cmdb.get()[host]["vars"].items(), key=lambda item: str(item[0])))

    host_nice_vars = yaml.dump(alphabetical_var_dict, default_flow_style=False, width=1000)

    if host_nice_vars == "{}":
        host_nice_vars = ""

    host_nice_vars = "---\n" + host_nice_vars

    return render_template("vars.html.j2", __thing="host_vars", __host=host, __vars=host_nice_vars)  # Return a webpage


@bp.route("/group/<string:group>")
def group(group: str) -> Response:
    """Return a JSON response for a group."""
    assert cmdb is not None

    cmdb_group_vars = cmdb.get_group(group)

    alphabetical_var_dict = dict(sorted(cmdb_group_vars.items(), key=lambda item: str(item[0])))

    group_nice_vars = yaml.dump(alphabetical_var_dict, default_flow_style=False, width=1000)

    group_nice_vars = group_nice_vars.strip()

    if group_nice_vars == "{}":
        group_nice_vars = ""

    group_nice_vars = "---\n" + group_nice_vars

    return render_template("vars.html.j2", __thing="group", __host=group, __vars=group_nice_vars)  # Return a webpage
