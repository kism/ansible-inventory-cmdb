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

    cmdb = AnsibleCMDB(current_app.config["cmdb"])  # Create an instance of our CMDB class


@bp.route("/")
def home() -> str:
    assert cmdb is not None

    inventories = cmdb.get_inventories()

    inventory_names = list(inventories.keys())

    return render_template("home.html.j2", __app_nice_name="Ansible Inventory CMDB", inventories=inventory_names)


# Flask homepage, generally don't have this as a blueprint.
@bp.route("/inventory/<string:inventory>")
def inventory(inventory: str) -> str:
    """Flask home."""
    assert cmdb is not None

    schema_mapping = dict(current_app.config["cmdb"][inventory]["schema_mapping"])

    print(type(schema_mapping))

    for mapping, nice_text in schema_mapping.items():
        logger.info(f"Mapping: {mapping} -> {nice_text}")

    inventory_dict = cmdb.get_inventory(inventory)

    for key, value in schema_mapping.items():
        print(value, end=", ")

    # for host, host_vars, in inventory_dict["hosts"].items():
    #     print(f"{host} -> {host_vars}", end=", ")

    for (
        host,
        host_vars,
    ) in inventory_dict["hosts"].items():
        # print(f"")
        print(f"{type(host)}, {type(host_vars)}")
        for key, value in schema_mapping.items():
            # print(f"{key}", end=", ")
            assert isinstance(host_vars, dict)
            assert isinstance(host_vars["vars"], dict)
            # if key in host_vars["vars"]:
                # print(f"{host_vars['vars'][key]}", end=", ")

    return render_template(
        "inventory.html.j2",
        __app_nice_name="Ansible Inventory CMDB",
        inventory_dict=inventory_dict,
        schema_mapping=schema_mapping,
    )  # Return a webpage


@bp.route("/inventory/<string:inventory>/host/<string:host>")
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


@bp.route("/inventory/<string:inventory>/group/<string:group>")
def group(inventory: str, group: str) -> Response:
    """Return a JSON response for a group."""
    assert cmdb is not None

    cmdb_group_vars = cmdb.get_group(inventory, group)

    alphabetical_var_dict = dict(sorted(cmdb_group_vars.items(), key=lambda item: str(item[0])))

    group_nice_vars = yaml.dump(alphabetical_var_dict, default_flow_style=False, width=1000)

    group_nice_vars = group_nice_vars.strip()

    if group_nice_vars == "{}":
        group_nice_vars = ""

    group_nice_vars = "---\n" + group_nice_vars

    return render_template("vars.html.j2", __thing="group", __host=group, __vars=group_nice_vars)  # Return a webpage
